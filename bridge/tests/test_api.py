import json
import threading
import time

import httpx
from strands.types.exceptions import ModelThrottledException

from kilta_bridge.chain import Link
from kilta_bridge.config import REPO_ROOT
from kilta_bridge.prompt import build_system_prompt

from .conftest import free_port
from .fakes import FailingModel, FlakyModel, Plan, ScriptedModel


def scripted(*plans: Plan) -> ScriptedModel:
    return ScriptedModel(list(plans))


def collect_events(url: str, stop_on: str, out: list[dict], ready: threading.Event) -> None:
    """Read server-sent events until one of type `stop_on` arrives."""
    with httpx.stream("GET", f"{url}/api/events", timeout=30) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        ready.set()
        kind = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                out.append(json.loads(line[6:]))
                if kind == stop_on:
                    return


def test_health_reports_the_mcp_server_and_the_model_chain(start_bridge):
    bridge = start_bridge([Link("scripted", scripted())])
    health = httpx.get(f"{bridge.url}/api/health", timeout=10).json()
    assert health["status"] == "ok" and health["demo_mode"] is True
    assert health["mcp"]["reachable"] is True
    assert health["mcp"]["protocol_version"] == "2025-11-25"
    assert {"start_repair", "next_step", "confirm_gate"} <= set(health["mcp"]["tools"])
    assert health["models"] == ["scripted"]


def test_health_degrades_when_the_mcp_server_is_down(start_bridge):
    bridge = start_bridge(
        [Link("scripted", scripted())], mcp_url=f"http://127.0.0.1:{free_port()}/mcp"
    )
    health = httpx.get(f"{bridge.url}/api/health", timeout=10).json()
    assert health["status"] == "degraded" and health["mcp"]["reachable"] is False


def test_a_turn_still_answers_when_the_mcp_server_is_down(start_bridge):
    model = scripted(Plan([("get_household", {})], say="Hi."))
    bridge = start_bridge([Link("scripted", model)], mcp_url=f"http://127.0.0.1:{free_port()}/mcp")
    resp = bridge.turn("Hey Alexa, connect me to Kilta.")
    assert resp["error"] and resp["speech"]  # a spoken apology, not a 500


def test_a_turn_returns_speech_card_tool_calls_and_state(start_bridge):
    model = scripted(
        Plan(
            [("start_repair", {"member_id": "priya", "description": "beeping"})],
            say="Quick safety check first.",
        )
    )
    bridge = start_bridge([Link("scripted", model)])
    resp = bridge.turn("My dishwasher is beeping")
    assert set(resp) >= {"speech", "card", "tool_calls", "state", "session_id", "model"}
    assert resp["speech"] == "Quick safety check first."
    assert resp["state"] == "SAFETY_CHECK" and resp["card"]["type"] == "safety_question"
    assert resp["session_id"].startswith("r-")
    call = resp["tool_calls"][0]
    assert call["name"] == "start_repair" and call["arguments"]["member_id"] == "priya"
    assert call["state"] == "SAFETY_CHECK" and call["ms"] >= 0 and call["say"]


def test_an_empty_model_reply_falls_back_to_the_tools_own_speech(start_bridge):
    bridge = start_bridge([Link("scripted", scripted(Plan([("get_household", {})], say=" ")))])
    resp = bridge.turn("hi")
    assert resp["speech"].startswith("Hi Priya")


def test_live_tool_calls_stream_over_sse(start_bridge):
    model = scripted(
        Plan(
            [
                ("start_repair", {"description": "beeping"}),
                ("get_repair_state", {}),
            ],
            say="Okay.",
        )
    )
    bridge = start_bridge([Link("scripted", model)])
    events: list[dict] = []
    ready = threading.Event()
    reader = threading.Thread(
        target=collect_events, args=(bridge.url, "turn_end", events, ready), daemon=True
    )
    reader.start()
    assert ready.wait(10)
    time.sleep(0.2)
    bridge.turn("My dishwasher is beeping")
    reader.join(10)
    kinds = [e["type"] for e in events]
    assert kinds == ["turn_start", "tool_call", "tool_call", "turn_end"]
    assert [e["name"] for e in events if e["type"] == "tool_call"] == [
        "start_repair",
        "get_repair_state",
    ]
    assert events[-1]["state"] == "SAFETY_CHECK" and events[1]["state"] == "SAFETY_CHECK"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


def test_sse_can_replay_recent_events_for_a_late_viewer(start_bridge):
    bridge = start_bridge([Link("scripted", scripted(Plan([("get_household", {})])))])
    bridge.turn("hi")
    events: list[dict] = []
    with httpx.stream("GET", f"{bridge.url}/api/events?replay=10", timeout=10) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
            if len(events) == 3:
                break
    assert [e["type"] for e in events] == ["turn_start", "tool_call", "turn_end"]


def test_switching_speaker_keeps_the_repair_and_tells_the_model_who_is_talking(start_bridge):
    model = scripted(
        Plan([("start_repair", {"member_id": "priya", "description": "beeping"})]),
        Plan([("get_repair_state", {})]),
    )
    bridge = start_bridge([Link("scripted", model)])
    first = bridge.turn("My dishwasher is beeping", "priya")
    second = bridge.turn("¿En qué estábamos?", "lucia")
    assert second["session_id"] == first["session_id"] and second["state"] == "SAFETY_CHECK"
    assert second["member_id"] == "lucia" and second["language"] == "es"
    context = model.seen_prompts[-1].splitlines()[0]
    assert "speaker=Lucia" in context and "language=es" in context
    assert "confidence=some" in context and f"active_session={first['session_id']}" in context
    assert (
        "speaker=Priya" in model.seen_prompts[0] and "confidence=beginner" in model.seen_prompts[0]
    )


def test_the_request_language_overrides_the_members_language(start_bridge):
    model = scripted(Plan(say="ok"))
    bridge = start_bridge([Link("scripted", model)])
    resp = bridge.turn("hello", "priya", language="es")
    assert resp["language"] == "es" and "language=es" in model.seen_prompts[0]


def test_the_system_prompt_carries_the_conversation_design_guide():
    prompt = build_system_prompt(REPO_ROOT / "docs")
    assert "calm, knowledgeable friend" in prompt  # from docs/conversation-design.md
    assert "danger_reported is true only when" in prompt


# --- reset -------------------------------------------------------------------------------------


def test_reset_clears_the_conversation_and_the_demo_data(start_bridge):
    model = scripted(
        Plan([("start_repair", {"description": "beeping"})]),
        Plan([("get_repair_state", {})]),
    )
    bridge = start_bridge([Link("scripted", model)])
    bridge.turn("My dishwasher is beeping")
    assert any((bridge.mcp.data_dir / "sessions").glob("r-*.json"))
    reset = httpx.post(f"{bridge.url}/api/reset", timeout=10)
    assert reset.status_code == 200 and reset.json()["ok"] is True
    assert not (bridge.mcp.data_dir / "sessions").exists()
    # The conversation restarted: the scripted model is back on its first plan, and no session
    # is remembered.
    health = httpx.get(f"{bridge.url}/api/health", timeout=10).json()
    assert health["state"] is None and health["session_id"] is None


def test_reset_is_refused_outside_demo_mode(start_bridge):
    bridge = start_bridge([Link("scripted", scripted())], demo_mode=False)
    assert httpx.post(f"{bridge.url}/api/reset", timeout=10).status_code == 403


def test_reset_brings_back_the_seeded_repair_history(start_bridge):
    plan = [
        ("start_repair", {"description": "beeping"}),
        ("safety_check", {"danger_reported": False}),
        ("identify_appliance", {"appliance_id": "dishwasher"}),
    ]
    bridge = start_bridge([Link("scripted", scripted(Plan(plan), Plan(plan)))])
    bridge.turn("My dishwasher is beeping")
    (bridge.mcp.data_dir / "state").mkdir(exist_ok=True)
    (bridge.mcp.data_dir / "state" / "repairs.json").write_text("{}")
    httpx.post(f"{bridge.url}/api/reset", timeout=10)
    assert not (bridge.mcp.data_dir / "state").exists()
    assert (bridge.mcp.data_dir / "appliances.json").exists()  # the seed data is never touched


# --- fallback ----------------------------------------------------------------------------------


def test_a_failing_primary_is_answered_by_the_next_model(start_bridge):
    primary = FailingModel(ModelThrottledException("429 rate limited"))
    backup = scripted(Plan([("get_household", {})], say="Hi from the backup."))
    bridge = start_bridge(
        [Link("primary", primary), Link("backup", backup)], retries=1, cooldown=60
    )
    events: list[dict] = []
    ready = threading.Event()
    reader = threading.Thread(
        target=collect_events, args=(bridge.url, "turn_end", events, ready), daemon=True
    )
    reader.start()
    ready.wait(10)
    time.sleep(0.2)
    resp = bridge.turn("hi")
    reader.join(10)
    assert resp["speech"] == "Hi from the backup." and resp["model"] == "backup"
    assert [f["model"] for f in resp["fallbacks"]] == ["primary", "primary"]
    assert primary.calls == 2
    assert {"model_retry", "model_fallback"} <= {e["type"] for e in events}


def test_a_flaky_primary_recovers_on_retry_without_falling_back(start_bridge):
    flaky = FlakyModel(
        scripted(Plan(say="Back again.")), failures=1, error=TimeoutError("timed out")
    )
    bridge = start_bridge([Link("primary", flaky), Link("backup", scripted(Plan(say="no")))])
    resp = bridge.turn("hi")
    assert resp["model"] == "primary" and resp["speech"] == "Back again."
    assert len(resp["fallbacks"]) == 1 and resp["fallbacks"][0]["retryable"] is True


def test_when_every_model_fails_the_turn_still_answers_and_recovers(start_bridge):
    working = scripted(Plan([("start_repair", {"description": "beeping"})], say="Safety first."))
    failing = FailingModel(ValueError("API key not valid"))
    chain_links = [
        Link("only", FlakyModel(working, failures=1, error=ValueError("API key not valid")))
    ]
    bridge = start_bridge(chain_links, retries=0)
    first = bridge.turn("My dishwasher is beeping")
    assert first["error"] == "all_models_failed" and first["speech"]
    assert first["state"] is None and first["tool_calls"] == []
    # The failed turn left no half-finished message behind, so the next one works.
    second = bridge.turn("My dishwasher is beeping")
    assert second["error"] is None and second["state"] == "SAFETY_CHECK"
    assert failing.calls == 0


# --- the model may not answer for the user -----------------------------------------------------


def test_the_model_cannot_answer_the_safety_question_in_the_turn_it_asks_it(start_bridge):
    plan = Plan(
        [
            ("start_repair", {"description": "beeping"}),
            ("safety_check", {"danger_reported": False, "details": "No, there's no burning"}),
            ("identify_appliance", {"appliance_type": "dishwasher"}),
        ],
        say="Is there any burning smell?",
    )
    bridge = start_bridge([Link("scripted", scripted(plan))])
    resp = bridge.turn("My dishwasher is beeping")
    calls = {c["name"]: c for c in resp["tool_calls"]}
    assert calls["safety_check"]["ok"] is False
    assert calls["safety_check"]["reason"] == "not_answered_by_user"
    assert resp["state"] == "SAFETY_CHECK"  # still waiting for the user
    assert calls["identify_appliance"]["refused"] is True  # the engine refused the skip too


def test_reporting_danger_is_allowed_in_the_same_turn_as_the_question(start_bridge):
    plan = Plan(
        [
            ("start_repair", {"description": "I smell burning"}),
            ("safety_check", {"danger_reported": True, "details": "I smell burning"}),
        ]
    )
    resp = start_bridge([Link("scripted", scripted(plan))]).turn("I smell burning")
    assert resp["state"] == "STOPPED" and resp["tool_calls"][1]["ok"] is True


def test_a_gate_cannot_be_confirmed_in_the_turn_it_is_asked(start_bridge):
    setup = [
        Plan([("start_repair", {"description": "beeping"})]),
        Plan(
            [
                ("safety_check", {"danger_reported": False}),
                ("identify_appliance", {"appliance_type": "dishwasher"}),
                ("find_manual", {}),
                ("quick_checks", {}),
            ]
        ),
        Plan([("diagnose", {"error_code": "E24"})]),
        Plan([("next_step", {}), ("confirm_gate", {"confirmed": True})]),
        Plan([("confirm_gate", {"confirmed": True}), ("next_step", {})]),
    ]
    bridge = start_bridge([Link("scripted", scripted(*setup))])
    for text in ("beeping", "no", "it's shut, E24"):
        bridge.turn(text)
    asked = bridge.turn("ready")
    assert asked["tool_calls"][1]["reason"] == "not_answered_by_user"
    assert asked["state"] == "STEPS" and asked["card"]["gate"]["confirmed"] is False
    answered = bridge.turn("it's unplugged")  # the user's own reply, in its own turn
    assert [c["ok"] for c in answered["tool_calls"]] == [True, True]
    assert answered["card"]["step_number"] == 2


def test_each_model_call_sees_only_the_tools_for_the_current_state(start_bridge):
    model = scripted(
        Plan([("start_repair", {"description": "beeping"})], say="Safety first."),
        Plan([("safety_check", {"danger_reported": False})], say="Which appliance?"),
    )
    bridge = start_bridge([Link("scripted", model)])
    bridge.turn("My dishwasher is beeping")
    first_call, after_start = model.seen_tools[0], model.seen_tools[1]
    assert "list_appliances" in first_call and "safety_check" in first_call  # no repair yet
    assert set(after_start) == {"get_household", "start_repair", "safety_check", "get_repair_state"}
    bridge.turn("No, nothing like that")
    # the new turn starts in SAFETY_CHECK; once cleared the next call is in IDENTIFY
    assert set(model.seen_tools[2]) == set(after_start)
    assert {"identify_appliance", "lookup_orders"} <= set(model.seen_tools[3])
    assert "next_step" not in model.seen_tools[3]


def test_a_safety_stop_is_spoken_by_the_engine_not_the_model(start_bridge):
    plan = Plan(
        [
            ("start_repair", {"description": "I smell burning"}),
            ("safety_check", {"danger_reported": True, "details": "I smell burning"}),
        ],
        say="Can you tell me more about the issue?",  # a small model ignoring the stop
    )
    resp = start_bridge([Link("scripted", scripted(plan))]).turn("I smell burning")
    assert resp["state"] == "STOPPED"
    assert resp["speech"].startswith("I'm stopping here, because safety comes first.")
    assert "emergency number" in resp["speech"] and "tell me more" not in resp["speech"]


def test_in_another_language_the_models_words_come_first_then_the_engines(start_bridge):
    plan = Plan(
        [
            ("start_repair", {"description": "huele a quemado"}),
            ("safety_check", {"danger_reported": True, "details": "huele a quemado"}),
        ],
        say="Por favor, aléjese del aparato.",
    )
    resp = start_bridge([Link("scripted", scripted(plan))]).turn("Huele a quemado", "lucia")
    assert resp["speech"].startswith("Por favor, aléjese del aparato.")
    assert "emergency number" in resp["speech"]


def test_an_empty_model_reply_is_asked_again_once(start_bridge):
    from .fakes import EmptyThenOk

    inner = scripted(Plan([("get_household", {})], say="Hi Priya."))
    flaky = EmptyThenOk(inner, empties=1)
    bridge = start_bridge([Link("small-model", flaky)])
    resp = bridge.turn("Hey Alexa, connect me to Kilta.")
    assert resp["error"] is None and resp["speech"] == "Hi Priya."
    assert [c["name"] for c in resp["tool_calls"]] == ["get_household"]


def test_two_empty_replies_end_in_a_spoken_apology_not_a_hang(start_bridge):
    from .fakes import EmptyThenOk

    flaky = EmptyThenOk(scripted(Plan(say="never reached")), empties=5)
    resp = start_bridge([Link("small-model", flaky)]).turn("hello")
    assert resp["speech"].startswith("Sorry, I lost my train of thought")


def test_an_invented_session_id_is_replaced_by_the_real_one(start_bridge):
    model = scripted(
        Plan([("start_repair", {"description": "beeping"})]),
        Plan([("get_repair_state", {"session_id": "123456"})]),
    )
    bridge = start_bridge([Link("scripted", model)])
    first = bridge.turn("My dishwasher is beeping")
    second = bridge.turn("where were we?")
    call = second["tool_calls"][0]
    assert call["ok"] and call["arguments"]["session_id"] == first["session_id"]
    assert second["state"] == "SAFETY_CHECK"


def test_a_cancelled_call_does_not_stay_in_the_conversation(start_bridge):
    plan1 = Plan(
        [
            ("start_repair", {"description": "beeping"}),
            ("safety_check", {"danger_reported": False}),
        ],
        say="Quick safety check first.",
    )
    model = scripted(plan1, Plan([("safety_check", {"danger_reported": False})], say="Thanks."))
    bridge = start_bridge([Link("scripted", model)])
    bridge.turn("My dishwasher is beeping")
    agent = bridge.app.state.kilta.agent
    blob = str(agent.messages)
    assert "safety_check" not in blob and "start_repair" in blob  # only the real call remains
    second = bridge.turn("No, nothing like that")
    assert second["tool_calls"][0]["ok"] and second["state"] == "IDENTIFY"
