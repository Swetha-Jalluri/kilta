"""Live golden tests: the real model chain, the real Strands agent, the real MCP server.

Not part of `make check`. Run with `make test-live` (needs GEMINI_API_KEY and GROQ_API_KEY in
.env). Calls are paced (KILTA_LIVE_PACE seconds between model calls, default 5) to stay inside
the free tiers; 429s are retried with backoff and then fall through the chain.

They assert tools (as an ordered subsequence), the exact engine state, and card facts. They
never assert wording, except that a withheld step's instruction must not be spoken.
"""

import os

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
    are the same on every machine."""
    env = {**dotenv_values(REPO_ROOT / ".env"), **os.environ}
    settings = Settings(
        gemini_api_key=env.get("GEMINI_API_KEY") or "", groq_api_key=env.get("GROQ_API_KEY") or ""
    )
    missing = [k for k in ("GEMINI_API_KEY", "GROQ_API_KEY") if not env.get(k)]
    if missing:
        pytest.skip(f"missing {', '.join(missing)} in .env")
    pace = float(env.get("KILTA_LIVE_PACE", 4))
    from dataclasses import replace

    return replace(
        settings,
        min_model_interval=pace,
        retries=3,
        retry_base_delay=3.0,
        turn_timeout=420.0,
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
        assert resp["state"] == "STOPPED" and resp["card"]["type"] == "safety_stop"
        assert not {"identify_appliance", "next_step"} & {c["name"] for c in resp["tool_calls"]}
    else:
        assert resp["state"] in {"IDENTIFY", "MANUAL"}


def test_live_a_bad_gemini_key_is_answered_by_groq(start_bridge):
    print("\nFallback proof: invalid Gemini key, Groq answers")
    settings = live_settings(gemini_api_key="not-a-real-key")
    bridge = start_bridge(settings=settings)
    first, second = run_turns(
        bridge,
        [SCENARIO_A[0], SCENARIO_A[1]],
    )
    for resp in (first, second):
        assert resp["model"].startswith("groq:"), resp["model"]
        assert resp["error"] is None
    assert first["fallbacks"][0]["model"].startswith("gemini:")
    assert first["fallbacks"][0]["retryable"] is False  # a bad key is skipped, not retried
    assert second["state"] == "SAFETY_CHECK"
