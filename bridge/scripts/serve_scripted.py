"""TEST ONLY. The bridge with a scripted fake model, for the browser (Playwright) tests.

Starts the real Kilta MCP server on a throwaway copy of the data, then the real bridge app, but the
"model" replays the golden scenarios A, B and C from tests/scenarios.py. No real model, no API key,
no Ollama. It also writes the scenario script as JSON so the browser test can type the same lines.

    uv run python scripts/serve_scripted.py
Environment: SCRIPTED_BRIDGE_PORT (8100), SCRIPTED_MCP_PORT (8791), SCRIPTED_WEB_ORIGINS,
SCRIPTED_JSON (where to write the script).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BRIDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE_ROOT))

import uvicorn  # noqa: E402

from kilta_bridge.app import create_app  # noqa: E402
from kilta_bridge.chain import FallbackModel, Link  # noqa: E402
from kilta_bridge.config import REPO_ROOT, Settings  # noqa: E402
from tests.fakes import Plan, ScriptedModel  # noqa: E402
from tests.scenarios import (  # noqa: E402
    NO_STATE,
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
    Turn,
    expand_scripted,
)

CONNECT = Plan(
    [("get_household", {"member_id": "priya"})], say="Hi Priya, I'm Kilta. What's going on?"
)


def script_json(name: str, turns: list[Turn], connect_first: bool) -> dict:
    rows = []
    for turn in turns:
        states = [turn.state] if isinstance(turn.state, str) else sorted(turn.state)
        rows.append(
            {
                "text": turn.text,
                "member": turn.member,
                "language": turn.language,
                "states": [None if s == NO_STATE else s for s in states],
                "card_type": turn.card.get("type"),
                "tools": [name for name, _ in turn.calls],
            }
        )
    return {"name": name, "connect_first": connect_first, "turns": rows}


class Scenarios(ScriptedModel):
    """Picks the scenario from the user's second message. Every conversation starts with the
    title screen's connect line, which gets the same first plan."""

    def __init__(self) -> None:
        self.a = expand_scripted(SCENARIO_A)
        self.b = expand_scripted(SCENARIO_B)
        self.c = expand_scripted(SCENARIO_C)
        super().__init__([])
        self.by_second_line = {
            self.a[1].text: [Plan(t.calls, t.say) for t in self.a],
            self.b[0].text: [CONNECT] + [Plan(t.calls, t.say) for t in self.b],
            self.c[0].text: [CONNECT] + [Plan(t.calls, t.say) for t in self.c],
        }

    def plan_for(self, turn: int, user_prompts: list[str]) -> Plan:
        if turn == 1:
            return CONNECT
        second = user_prompts[1].split("\n", 1)[-1]
        return self.by_second_line[second][turn - 1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    bridge_port = int(os.environ.get("SCRIPTED_BRIDGE_PORT", 8100))
    mcp_port = int(os.environ.get("SCRIPTED_MCP_PORT", 8791))
    origins = tuple(
        o for o in os.environ.get("SCRIPTED_WEB_ORIGINS", "http://localhost:5273").split(",") if o
    )
    work = Path(tempfile.mkdtemp(prefix="kilta-scripted-"))
    data = work / "data"
    shutil.copytree(REPO_ROOT / "data", data, ignore=shutil.ignore_patterns("sessions", "state"))
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["KILTA_DATA_DIR"] = str(data)
    server = subprocess.Popen(
        ["uv", "run", "--frozen", "--project", str(REPO_ROOT / "server"), "kilta-server",
         "--port", str(mcp_port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # fmt: skip
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", mcp_port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        server.kill()
        sys.exit("the MCP server did not start")

    out = os.environ.get("SCRIPTED_JSON")
    if out:
        model = Scenarios()
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(
            json.dumps(
                {
                    "A": script_json("A", model.a, connect_first=True),
                    "B": script_json("B", model.b, connect_first=False),
                    "C": script_json("C", model.c, connect_first=False),
                },
                indent=2,
            )
        )
    settings = Settings(
        mcp_url=f"http://127.0.0.1:{mcp_port}/mcp",
        data_dir=data,
        demo_mode=True,
        cors_origins=origins,
    )
    app = create_app(settings, FallbackModel([Link("scripted", Scenarios())]))
    try:
        uvicorn.run(app, host="127.0.0.1", port=bridge_port, log_level="warning")
    finally:
        server.terminate()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
