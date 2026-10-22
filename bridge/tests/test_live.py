"""Live golden tests: the real model chain, the real Strands agent, the real MCP server.

Not part of `make check`. Run with `make test-live` (needs GEMINI_API_KEY and GROQ_API_KEY in
.env). Calls are paced (KILTA_LIVE_PACE seconds between model calls, default 5) to stay inside
the free tiers; 429s are retried with backoff and then fall through the chain.

They assert tools (as an ordered subsequence), the exact engine state, and card facts. They
never assert wording, except that a withheld step's instruction must not be spoken.
"""

import os
from dataclasses import replace

import httpx
import pytest
from dotenv import dotenv_values

from kilta_bridge.config import REPO_ROOT, Settings

from .scenarios import (
    DANGER_ANSWERS,
    DANGER_SETUP,
    NO_STATE,
    SCENARIO_A,
    SCENARIO_B,
    SCENARIO_C,
    SCENARIO_C_CONFIRM,
    verify,
)

pytestmark = pytest.mark.live


def live_settings(**overrides) -> Settings:
    """Keys come from .env or the environment. Model IDs are the committed defaults, so the runs
    are the same on every machine.

    KILTA_LIVE_MODEL picks one link so a run touches only that model's quota:
    primary | groq | fallback | ollama (or chain, the default, for the whole fallback chain).
    """
    env = {**dotenv_values(REPO_ROOT / ".env"), **os.environ}
    only = (env.get("KILTA_LIVE_MODEL") or "chain").strip().lower()
    only = "" if only == "chain" else only
    needed = {
        "": ("GEMINI_API_KEY", "GROQ_API_KEY"),
        "primary": ("GEMINI_API_KEY",),
        "fallback": ("GEMINI_API_KEY",),
        "groq": ("GROQ_API_KEY",),
        "ollama": (),
    }[only]
    if missing := [k for k in needed if not env.get(k)]:
        pytest.skip(f"missing {', '.join(missing)} in .env")
    pace = 0.0 if only == "ollama" else float(env.get("KILTA_LIVE_PACE", 4))  # local: no pacing
    settings = Settings(
        gemini_api_key=env.get("GEMINI_API_KEY") or "", groq_api_key=env.get("GROQ_API_KEY") or ""
    )
    return replace(
        settings,
        min_model_interval=pace,
        retries=3,
        retry_base_delay=3.0,
        turn_timeout=420.0,
        model_only=only,
        **overrides,
    )


def run_turns(bridge, turns, started: float | None = None) -> list[dict]:
    responses = []
    for number, turn in enumerate(turns, 1):
        resp = bridge.turn(turn.text, turn.member, turn.language)
        names = " > ".join(c["name"] for c in resp["tool_calls"]) or "(no tools)"
        print(
            f"  {number:>2}. [{resp['model']}] {resp['elapsed_ms'] / 1000:5.1f}s "
            f"{(resp['state'] or NO_STATE):<14} {names}"
        )
        print(f"      user : {turn.text}")
        print(f"      kilta: {resp['speech']}")
        verify(resp, turn)
        assert len(resp["speech"].split()) <= 100, "spoken reply is too long for voice"
        responses.append(resp)
    return responses


def test_live_scenario_a_dishwasher_e24_fixed(start_bridge):
    print("\nScenario A: dishwasher E24, fixed at home")
    bridge = start_bridge(settings=live_settings())
    run_turns(bridge, SCENARIO_A)


def test_live_scenario_b_washer_e31_landlord_handoff(start_bridge):
    print("\nScenario B: washer E31, renter handoff")
    bridge = start_bridge(settings=live_settings())
    run_turns(bridge, SCENARIO_B)


def test_live_scenario_c_danger_stops_everything(start_bridge):
    print("\nScenario C: burning smell")
    bridge = start_bridge(settings=live_settings())
    (first,) = run_turns(bridge, SCENARIO_C)
    if first["state"] != "STOPPED":  # the model asked before stopping: answer it
        run_turns(bridge, [SCENARIO_C_CONFIRM])
    assert httpx.get(f"{bridge.url}/api/health", timeout=10).json()["state"] == "STOPPED"


@pytest.mark.parametrize("answer, member, language, danger", DANGER_ANSWERS)
def test_live_safety_answers_become_explicit_booleans(
    start_bridge, answer, member, language, danger
):
    print(f"\nSafety answer {answer!r} -> danger_reported={danger}")
    bridge = start_bridge(settings=live_settings())
    run_turns(bridge, [DANGER_SETUP])
    resp = bridge.turn(answer, member, language)
    checks = [c for c in resp["tool_calls"] if c["name"] == "safety_check"]
    print(f"  {[c['arguments'] for c in checks]} -> {resp['state']}")
    assert checks, f"no safety_check call for {answer!r}: {[c['name'] for c in resp['tool_calls']]}"
    assert checks[-1]["arguments"]["danger_reported"] is danger
    if danger:
        assert resp["state"] == "STOPPED"  # the model may go on to offer a landlord message
        assert not {"identify_appliance", "next_step"} & {c["name"] for c in resp["tool_calls"]}
    else:
        assert resp["state"] in {"IDENTIFY", "MANUAL", "QUICK_CHECKS"}


def test_live_a_bad_gemini_key_is_answered_by_groq(start_bridge):
    """Fallback proof. Groq's free model is slow and less strict about the flow, so this only
    asserts who answered and how the chain behaved, not the engine state."""
    print("\nFallback proof: invalid Gemini key, Groq answers")
    bridge = start_bridge(settings=live_settings(gemini_api_key="not-a-real-key"))
    first, second = run_turns(bridge, [SCENARIO_A[0]]) + [None]
    second = bridge.turn(SCENARIO_A[1].text, SCENARIO_A[1].member)
    print(f"  2. [{second['model']}] {second['speech']}")
    for resp in (first, second):
        assert resp["model"].startswith("groq:"), resp["model"]
        assert resp["error"] is None and resp["speech"]
    assert first["fallbacks"][0]["model"] == "gemini:gemini-3.5-flash"
    assert first["fallbacks"][0]["retryable"] is False  # a bad key is skipped, not retried
    assert first["fallbacks"][0]["error"].startswith("ClientError: 400")
