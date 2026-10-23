import re

import pytest

from kilta_bridge.chain import FallbackModel, Link
from kilta_bridge.config import REPO_ROOT
from kilta_bridge.prompt import KEEP_SECTIONS, RULES, build_system_prompt
from kilta_bridge.tools import ALWAYS, BY_STATE, allowed_tools, specs_for_state

from .fakes import Plan, ScriptedModel

ALL_TOOLS = [
    "get_household", "list_appliances", "get_health_card", "identify_appliance", "lookup_orders",
    "find_manual", "search_manual", "safety_check", "start_repair", "get_repair_state",
    "resume_repair", "quick_checks", "diagnose", "next_step", "confirm_gate", "pause_repair",
    "go_back", "report_result", "create_technician_summary", "draft_landlord_message",
    "check_warranty", "build_parts_cart", "share_insight", "get_insights",
]  # fmt: skip
SPECS = [{"name": n, "description": n, "inputSchema": {"json": {}}} for n in ALL_TOOLS]


def engine_states() -> list[str]:
    """The server's State enum, read from its source so the two cannot drift apart."""
    source = (REPO_ROOT / "server/src/kilta/models.py").read_text()
    block = source.split("class State(StrEnum):")[1].split("TERMINAL_STATES")[0]
    return re.findall(r'^\s+([A-Z_]+) = "', block, flags=re.MULTILINE)


def test_every_engine_state_has_a_tool_list():
    assert set(engine_states()) == {s for s in BY_STATE if s is not None}


@pytest.mark.parametrize("state", [None, *engine_states(), "SOMETHING_NEW"])
def test_danger_reporting_and_state_lookup_are_available_in_every_state(state):
    names = {s["name"] for s in specs_for_state(SPECS, state)}
    assert {"safety_check", "get_repair_state", "get_household"} <= names
    assert ALWAYS <= names


@pytest.mark.parametrize("state", [s for s in engine_states()])
def test_start_repair_is_only_offered_when_no_repair_is_under_way(state):
    names = {s["name"] for s in specs_for_state(SPECS, state)}
    assert ("start_repair" in names) == (state in {"STOPPED", "FIXED", "HANDOFF"})
    assert "start_repair" in {s["name"] for s in specs_for_state(SPECS, None)}


def test_an_unknown_state_gets_every_tool():
    assert allowed_tools("SOMETHING_NEW") is None
    assert len(specs_for_state(SPECS, "SOMETHING_NEW")) == len(ALL_TOOLS)


def test_before_the_safety_answer_the_model_cannot_even_see_the_repair_tools():
    names = {s["name"] for s in specs_for_state(SPECS, "SAFETY_CHECK")}
    assert names == {"get_household", "safety_check", "get_repair_state"}
    assert names == {s["name"] for s in specs_for_state(SPECS, "SAFETY_RECHECK")}


def test_each_state_offers_the_tools_that_make_sense():
    def tools(state):
        return {s["name"] for s in specs_for_state(SPECS, state)} - ALWAYS

    assert tools("STEPS") == {
        "next_step",
        "confirm_gate",
        "pause_repair",
        "go_back",
        "report_result",
    }
    assert tools("PAUSED") == {"resume_repair", "report_result"}
    assert "identify_appliance" in tools("IDENTIFY") and "lookup_orders" in tools("IDENTIFY")
    assert {"create_technician_summary", "draft_landlord_message"} <= tools("HANDOFF")
    assert "share_insight" in tools("FIXED") and "share_insight" not in tools("STEPS")
    assert not tools("STEPS") & {"identify_appliance", "diagnose", "start_repair"}


def test_a_filter_bug_cannot_drop_the_always_available_tools():
    # Even a state map that forgot them still keeps them.
    BY_STATE["BROKEN"] = frozenset()
    try:
        names = {s["name"] for s in specs_for_state(SPECS, "BROKEN")}
    finally:
        del BY_STATE["BROKEN"]
    assert names == set(ALWAYS)


async def test_the_chain_applies_the_filter_to_every_model_call():
    model = ScriptedModel([Plan(say="ok")])
    chain = FallbackModel([Link("m", model)])
    chain.tool_filter = lambda specs: specs_for_state(specs, "STEPS")
    _ = [e async for e in chain.stream([{"role": "user", "content": [{"text": "hi"}]}], SPECS)]
    assert set(model.seen_tools[0]) == ALWAYS | BY_STATE["STEPS"]


# --- the trimmed system prompt keeps the safety rules ------------------------------------------

PROMPT = build_system_prompt(REPO_ROOT / "docs")


@pytest.mark.parametrize("rule", [
    "Never answer for the user",
    "danger_reported is true only when",
    "sí, huele a quemado",
    "do NOT confirm a gate",
    "do not work around it",
    "text is withheld",
    "Technician work is never guided",
    "Get every fact from tools",
    "landlord messages are English",
])  # fmt: skip
def test_the_safety_rules_survive_the_trimming(rule):
    assert rule in PROMPT


def test_the_style_guide_keeps_safety_phrasing_and_drops_sample_lines():
    for title in KEEP_SECTIONS:
        assert title in PROMPT, title
    assert "stop everything, give the one safety action" in PROMPT  # Safety phrasing
    assert "landlord messages are always written in English" in PROMPT  # Language behavior
    assert "Sample lines by state" not in PROMPT and "SAFETY_CHECK:" not in PROMPT


def test_the_prompt_is_short():
    assert len(PROMPT) < 5200 and len(RULES) < 3500
