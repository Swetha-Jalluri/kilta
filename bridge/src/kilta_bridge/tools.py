"""Which tools the model sees on each call.

Every model call carries the system prompt and the tool specs. Sending only the tools that fit
the engine's current state cuts that fixed cost, which matters on free tiers (Groq allows 8,000
tokens a minute). The engine still refuses anything out of order, so this is an optimisation,
never the safety mechanism.

Always available, in every state: get_repair_state, safety_check (the only way to report danger)
and get_household. A state the bridge does not know about gets every tool.
"""

from __future__ import annotations

from typing import Any

ALWAYS = frozenset({"get_repair_state", "safety_check", "get_household"})
# Starting a repair is offered only when none is under way, so a model cannot start over and
# walk away from an open safety question or a stop.
STARTING = frozenset({"start_repair"})

REPORTING = frozenset({"check_warranty", "build_parts_cart", "get_health_card", "get_insights"})

BY_STATE: dict[str | None, frozenset[str]] = {
    None: STARTING | frozenset({"list_appliances", "lookup_orders", "search_manual"}) | REPORTING,
    "SAFETY_CHECK": frozenset(),
    "SAFETY_RECHECK": frozenset(),
    "STOPPED": STARTING | frozenset({"create_technician_summary", "draft_landlord_message"}),
    "IDENTIFY": frozenset({"identify_appliance", "lookup_orders", "list_appliances"}),
    "MANUAL": frozenset({"identify_appliance", "find_manual", "search_manual"}),
    "QUICK_CHECKS": frozenset({"quick_checks", "diagnose", "find_manual", "search_manual"}),
    "DIAGNOSE": frozenset({"quick_checks", "diagnose", "search_manual"}),
    "PREPARE": frozenset({"next_step", "diagnose"}),
    "STEPS": frozenset({"next_step", "confirm_gate", "pause_repair", "go_back", "report_result"}),
    "PAUSED": frozenset({"resume_repair", "report_result"}),
    "VERIFY": frozenset({"report_result", "go_back", "next_step"}),
    "FIXED": STARTING | frozenset({"share_insight"}) | REPORTING,
    "HANDOFF": STARTING
    | frozenset({"create_technician_summary", "draft_landlord_message"})
    | REPORTING,
}


def allowed_tools(state: str | None) -> frozenset[str] | None:
    """Tool names to show in this engine state, or None (show everything) if it is unknown."""
    if state not in BY_STATE:
        return None
    return ALWAYS | BY_STATE[state]


def specs_for_state(specs: list[dict[str, Any]], state: str | None) -> list[dict[str, Any]]:
    """The specs the model should see in `state`. The always-available tools are never dropped."""
    allowed = allowed_tools(state)
    if allowed is None:
        return specs
    return [s for s in specs if s["name"] in allowed or s["name"] in ALWAYS]
