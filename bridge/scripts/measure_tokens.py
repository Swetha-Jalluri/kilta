"""Measure what one model call costs: system prompt + tool specs, per engine state.

    uv run python scripts/measure_tokens.py            # needs a running Kilta server (`make dev`)
    uv run python scripts/measure_tokens.py --measure  # also asks Groq for the real token count

Token counts come from Groq's `prompt_tokens` (no local tokenizer is installed), one request per
state. Conversation history is not included: this is the fixed cost of every model call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from kilta_bridge.config import REPO_ROOT, Settings
from kilta_bridge.prompt import build_system_prompt

STATES = [None, "SAFETY_CHECK", "SAFETY_RECHECK", "STOPPED", "IDENTIFY", "MANUAL", "QUICK_CHECKS",
          "DIAGNOSE", "PREPARE", "STEPS", "PAUSED", "VERIFY", "FIXED", "HANDOFF"]  # fmt: skip


async def list_specs(url: str) -> list[dict]:
    async with streamable_http_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
    return [
        {"name": t.name, "description": t.description or "", "inputSchema": {"json": t.inputSchema}}
        for t in tools
    ]


def openai_tools(specs: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["inputSchema"]["json"],
            },
        }
        for s in specs
    ]


def groq_prompt_tokens(settings: Settings, system: str, specs: list[dict]) -> int:
    body = {
        "model": settings.model_groq,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": "hi"}],
        "tools": openai_tools(specs),
        "max_tokens": 1,
    }
    request = urllib.request.Request(
        f"{settings.groq_base_url}/chat/completions",
        json.dumps(body).encode(),
        {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.groq_api_key}",
            "User-Agent": "kilta-dev/0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["usage"]["prompt_tokens"]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://localhost:8765/mcp")
    parser.add_argument("--measure", action="store_true", help="call Groq for a real token count")
    args = parser.parse_args()
    load_dotenv(REPO_ROOT / ".env")
    settings = Settings.from_env()
    system = build_system_prompt(settings.docs_dir)
    specs = await list_specs(args.server)

    try:  # present after the trimming work; absent in the original
        from kilta_bridge.tools import allowed_tools, specs_for_state
    except ImportError:
        allowed_tools = specs_for_state = None

    print(f"system prompt: {len(system)} chars")
    if not args.measure:
        print("(add --measure for real token counts from Groq; needs GROQ_API_KEY)")
        return
    rows: list[tuple[str, int, int]] = []
    rows.append(("all tools", len(specs), measure(settings, system, specs)))
    if allowed_tools is not None:
        for state in STATES:
            chosen = specs_for_state(specs, state)
            rows.append((str(state), len(chosen), measure(settings, system, chosen)))
    print(f"\n{'state':<16}{'tools':>6}{'tokens per call':>17}")
    for name, count, tokens in rows:
        print(f"{name:<16}{count:>6}{tokens:>17}")


def measure(settings: Settings, system: str, specs: list[dict]) -> int:
    """Real prompt tokens, from Groq. Waits out its 8,000 tokens-per-minute limit."""
    for _ in range(8):
        try:
            return groq_prompt_tokens(settings, system, specs)
        except urllib.error.HTTPError as error:
            if error.code != 429:
                raise
            time.sleep(15)
    raise RuntimeError("Groq kept rate limiting")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
