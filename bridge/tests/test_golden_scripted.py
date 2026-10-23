"""Golden conversations replayed through the real bridge and the real MCP server.

The model is scripted, so these prove the plumbing: Strands, the MCP client over Streamable
HTTP, the engine rules, tool order, card and state. The live tests do the same with real models.
"""

import pytest

from kilta_bridge.chain import Link

from .fakes import ScriptedModel
from .scenarios import SCENARIO_A, SCENARIO_B, SCENARIO_C, expand_scripted, plans, play


@pytest.mark.parametrize("name, turns", [("A", SCENARIO_A), ("B", SCENARIO_B), ("C", SCENARIO_C)])
def test_golden_scenario(name, turns, start_bridge):
    turns = expand_scripted(turns)
    bridge = start_bridge([Link("scripted", ScriptedModel(plans(turns)))])
    play(bridge, turns, live=False)


def test_scenario_a_tool_order_matches_the_demo_script(start_bridge):
    turns = expand_scripted(SCENARIO_A)
    bridge = start_bridge([Link("scripted", ScriptedModel(plans(turns)))])
    seen = []
    for turn in turns:
        resp = bridge.turn(turn.text, turn.member, turn.language)
        seen.extend(c["name"] for c in resp["tool_calls"])
    assert seen[:10] == [
        "get_household",
        "start_repair",
        "safety_check",
        "identify_appliance",
        "find_manual",
        "diagnose",
        "next_step",
        "next_step",
        "confirm_gate",
        "next_step",
    ]
    assert seen[-2:] == ["report_result", "share_insight"]
    assert seen.count("pause_repair") == 1 and seen.count("resume_repair") == 1


def test_scenario_c_never_offers_repair_steps(start_bridge):
    bridge = start_bridge([Link("scripted", ScriptedModel(plans(SCENARIO_C)))])
    resp = bridge.turn(SCENARIO_C[0].text)
    assert resp["state"] == "STOPPED" and resp["card"]["type"] == "safety_stop"
    assert [c["name"] for c in resp["tool_calls"]] == ["start_repair", "safety_check"]
