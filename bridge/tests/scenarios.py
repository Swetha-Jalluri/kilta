"""Golden conversations from docs/demo-script.md, shared by the scripted and the live tests.

Each turn lists what must be true afterwards: an ordered subsequence of tools (extra read-only
calls are fine), the exact engine state, and a few facts from the card. Wording is never
asserted. `calls` and `say` script the fake model in the always-on tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

NO_STATE = "-"  # no repair has started, so the engine reports no state
HIDDEN_BEFORE_GATE = ("sump", "debris", "sumidero", "residuos", "restos", "escombros")


@dataclass
class Turn:
    text: str
    member: str = "priya"
    language: str | None = None
    tools: list[str] = field(default_factory=list)
    any_of: list[list[str]] | None = None  # alternatives to `tools`
    forbid: list[str] = field(default_factory=list)
    state: str | set[str] = NO_STATE
    args: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    last_refused: str | None = None  # the last tool call was refused with this reason
    # "Next" without confirming: the gate must hold. Any next_step the model makes is refused,
    # it never confirms for the user, and the step does not move. Declining to call next_step
    # at all (and asking for the confirmation again) is just as safe.
    gate_held: bool = False
    # Say this again until `repeat_until(response, last_card)` is true. A model may take a step
    # on its own after a confirmation, so the number of "next"s is not fixed. `scripted_repeats`
    # is how many times the scripted-model tests replay it.
    repeat_until: Callable[[dict[str, Any], dict[str, Any] | None], bool] | None = None
    max_repeats: int = 8
    scripted_repeats: int = 1
    speech_forbids: tuple[str, ...] = ()
    card: dict[str, Any] = field(default_factory=dict)  # card keys that must match
    check: Callable[[dict[str, Any]], None] | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # scripted model
    say: str = "Okay."


def subsequence(wanted: list[str], actual: list[str]) -> bool:
    it = iter(actual)
    return all(name in it for name in wanted)


def verify(resp: dict[str, Any], turn: Turn) -> None:
    names = [c["name"] for c in resp["tool_calls"]]
    assert resp["error"] is None, f"turn failed: {resp['error']} ({turn.text!r})"
    options = turn.any_of or [turn.tools]
    assert any(subsequence(o, names) for o in options), (
        f"{turn.text!r}: expected tools {options}, got {names}"
    )
    for name in turn.forbid:
        assert name not in names, f"{turn.text!r}: {name} must not be called (got {names})"
    allowed = {turn.state} if isinstance(turn.state, str) else set(turn.state)
    got = resp["state"] if resp["state"] is not None else NO_STATE
    assert got in allowed, f"{turn.text!r}: expected state {allowed}, got {got}"
    for tool, subset in turn.args:
        matching = [c for c in resp["tool_calls"] if c["name"] == tool]
        assert any(all(c["arguments"].get(k) == v for k, v in subset.items()) for c in matching), (
            f"{turn.text!r}: no {tool} call with {subset}; saw {[c['arguments'] for c in matching]}"
        )
    if turn.last_refused:
        last = resp["tool_calls"][-1]
        assert last["refused"] and last["reason"] == turn.last_refused, (
            f"{turn.text!r}: last call {last['name']} was not refused with {turn.last_refused}: "
            f"{last['reason']}"
        )
    if turn.gate_held:
        assert "confirm_gate" not in names, f"{turn.text!r}: the model confirmed the gate itself"
        for call in resp["tool_calls"]:
            if call["name"] == "next_step":
                assert call["refused"] and call["reason"] in (
                    "gate_unconfirmed",
                    "not_answered_by_user",
                )
    for key, value in turn.card.items():
        assert resp["card"] is not None, f"{turn.text!r}: no card"
        assert resp["card"].get(key) == value, (
            f"{turn.text!r}: card[{key!r}] is {resp['card'].get(key)!r}, wanted {value!r}"
        )
    lowered = resp["speech"].lower()
    for word in turn.speech_forbids:
        assert word not in lowered, f"{turn.text!r}: speech leaked {word!r}: {resp['speech']!r}"
    if turn.check:
        turn.check(resp)


def _page(n: int) -> Callable[[dict[str, Any]], None]:
    def check(resp: dict[str, Any]) -> None:
        assert resp["card"]["source"]["page"] == n

    return check


def _text_starts(prefix: str) -> Callable[[dict[str, Any]], None]:
    def check(resp: dict[str, Any]) -> None:
        assert resp["card"]["text"].startswith(prefix)

    return check


def _step_in(*steps: int | None) -> Callable[[dict[str, Any]], None]:
    """The card shows one of these steps. None also allows the verify card (already past 8)."""

    def check(resp: dict[str, Any]) -> None:
        card = resp["card"]
        if None in steps and card["type"] == "verify":
            return
        assert card["step_number"] in steps, card.get("step_number")

    return check


def _revealed_or_moved_on(step: int, prefix: str) -> Callable[[dict[str, Any]], None]:
    def check(resp: dict[str, Any]) -> None:
        card = resp["card"]
        if card["step_number"] == step:
            assert card["text"] and card["text"].startswith(prefix) and not card["text_withheld"]
        else:
            assert card["step_number"] == step + 1 and not card["text_withheld"]

    return check


def _withheld(step: int, only_if_card: bool = False) -> Callable[[dict[str, Any]], None]:
    def check(resp: dict[str, Any]) -> None:
        if only_if_card and resp["card"] is None:
            return
        assert resp["card"]["step_number"] == step
        assert resp["card"]["text"] is None and resp["card"]["text_withheld"] is True

    return check


def _landlord(resp: dict[str, Any]) -> None:
    body = resp["card"]["body"]
    for expected in ("E31", "WM-500-R4T9", "page 24", "Lakeview"):
        assert expected in body, f"landlord message is missing {expected!r}"


def _fixed_repeat(resp: dict[str, Any]) -> None:
    assert resp["card"]["repeat_count"] == 2  # the seeded 2025-11-02 E24 repair counts


STEP_1 = {"type": "step", "step_number": 1}

# The engine confirms an appliance the user already named, so identify_appliance is optional.

# --- Scenario A: dishwasher E24, fixed at home (Priya, then Lucia) -----------------------------

SCENARIO_A = [
    Turn(
        "Hey Alexa, connect me to Kilta.",
        tools=["get_household"],
        state=NO_STATE,
        calls=[("get_household", {"member_id": "priya"})],
        say="Hi Priya, I'm Kilta, your home repair friend. What's going on today?",
    ),
    Turn(
        "My dishwasher is beeping and there's water at the bottom.",
        tools=["start_repair"],
        state="SAFETY_CHECK",
        card={"type": "safety_question"},
        calls=[
            (
                "start_repair",
                {"member_id": "priya", "description": "dishwasher beeping, water at the bottom"},
            )
        ],
        say="That sounds frustrating. Quick safety check: do you smell burning or see sparks?",
    ),
    Turn(
        "No, nothing like that.",
        tools=["safety_check"],
        state="MANUAL",
        args=[("safety_check", {"danger_reported": False})],
        card={"type": "appliance", "appliance_id": "dishwasher"},
        calls=[
            ("safety_check", {"danger_reported": False, "details": "no"}),
            ("identify_appliance", {"appliance_type": "dishwasher"}),
        ],
        say="Good. Is this your Kelvara dishwasher in the kitchen?",
    ),
    Turn(
        "Yes.",
        tools=["find_manual"],
        state="QUICK_CHECKS",
        card={"type": "quick_checks"},
        calls=[("find_manual", {})],
        say="I found the manual, page 16. Is the door clicked fully shut?",
    ),
    Turn(
        "It's shut. The screen says E24.",
        tools=["diagnose"],
        state="PREPARE",
        card={"type": "diagnosis", "error_code": "E24"},
        check=_page(18),
        calls=[("diagnose", {"error_code": "E24"})],
        say="E24 means it isn't draining, most likely the filter. About 15 minutes. Ready?",
    ),
    Turn(
        "Okay, ready.",
        tools=["next_step"],
        state="STEPS",
        card=STEP_1,
        calls=[("next_step", {})],
        say="Step 1 of 8. Turn it off and unplug it. Tell me when it's unplugged.",
    ),
    Turn(
        "Next.",
        state="STEPS",
        gate_held=True,
        calls=[("next_step", {})],
        say="Not yet, safety first. Tell me once it's unplugged. I'll wait right here.",
    ),
    Turn(
        "It's unplugged.",
        tools=["confirm_gate", "next_step"],
        state="STEPS",
        args=[("confirm_gate", {"confirmed": True})],
        card={"step_number": 2},
        calls=[("confirm_gate", {"confirmed": True}), ("next_step", {})],
        say="Thanks. Step 2 of 8. Lay a towel in front of the door.",
    ),
    Turn(
        "¿Puedes decirlo en español?",
        member="lucia",
        language="es",
        any_of=[["next_step"], ["get_repair_state"]],
        state="STEPS",
        card={"step_number": 2},
        calls=[("next_step", {"repeat": True})],
        say="Claro. Paso 2 de 8. Pon una toalla frente a la puerta.",
    ),
    Turn(
        "Espera, alguien está en la puerta.",
        member="lucia",
        language="es",
        tools=["pause_repair"],
        state="PAUSED",
        card={"type": "paused"},
        calls=[("pause_repair", {})],
        say="Sin problema. Estamos en pausa en el paso 2.",
    ),
    Turn(
        "Kilta, sigamos.",
        member="lucia",
        language="es",
        tools=["resume_repair"],
        state="STEPS",
        card={"step_number": 2},
        check=lambda r: (
            r["card"]["gate"]
            == {"prompt": "Is the dishwasher unplugged?", "kind": "after", "confirmed": False}
        ),
        calls=[("resume_repair", {})],
        say="Bienvenida. Nos quedamos en el paso 2. ¿Sigue desenchufado el lavavajillas?",
    ),
    Turn(
        "Sí, sigue desenchufado.",
        member="lucia",
        language="es",
        tools=["confirm_gate"],
        state="STEPS",
        args=[("confirm_gate", {"confirmed": True})],
        calls=[("confirm_gate", {"confirmed": True})],
        say="Gracias. Dime cuando estés lista.",
    ),
    Turn(
        "Siguiente.",
        member="lucia",
        language="es",
        state="STEPS",
        speech_forbids=HIDDEN_BEFORE_GATE,  # steps 3 to 5 must not say anything about step 6
        repeat_until=lambda resp, card: bool(card and card.get("text_withheld")),
        scripted_repeats=4,  # steps 3, 4, 5, then 6 withheld
        calls=[("next_step", {})],
        say="Paso. Antes de decirte este paso: ¿sigue apagada la corriente?",
    ),
    Turn(
        "Sí, la corriente sigue apagada.",
        member="lucia",
        language="es",
        tools=["confirm_gate"],
        state="STEPS",
        args=[("confirm_gate", {"confirmed": True})],
        # The gate is open, so the step is revealed. The model may also have gone on to step 7.
        check=_revealed_or_moved_on(6, "Check the sump"),
        calls=[("confirm_gate", {"confirmed": True})],
        say="Gracias. Revisa el sumidero.",
    ),
    Turn(
        "Siguiente.",
        member="lucia",
        language="es",
        state={"STEPS", "VERIFY"},
        repeat_until=lambda resp, card: bool(card and card.get("type") == "verify"),
        scripted_repeats=3,  # steps 7 and 8, then the verify question
        calls=[("next_step", {})],
        say="Siguiente paso.",
    ),
    Turn(
        "It drains now!",
        member="priya",
        tools=["report_result"],
        state="FIXED",
        args=[("report_result", {"outcome": "fixed"})],
        card={"type": "fixed"},
        check=_fixed_repeat,
        calls=[("report_result", {"outcome": "fixed"})],
        say="It's draining. You fixed that yourself. Want to share what worked, anonymously?",
    ),
    Turn(
        "Sure, share it.",
        tools=["share_insight"],
        state="FIXED",
        args=[("share_insight", {"consent": True})],
        card={"type": "insight_shared"},
        calls=[("share_insight", {"consent": True})],
        say="Thank you. Shared anonymously.",
    ),
]

# --- Scenario B: washer E31 after the filter clean, renter handoff -----------------------------

SCENARIO_B = [
    Turn(
        "The washer says E31.",
        tools=["start_repair"],
        state="SAFETY_CHECK",
        calls=[("start_repair", {"member_id": "priya", "description": "washer says E31"})],
        say="That's frustrating. Quick safety check: any burning smell or sparks?",
    ),
    Turn(
        "No, nothing like that.",
        tools=["safety_check"],
        state="MANUAL",
        args=[("safety_check", {"danger_reported": False})],
        card={"type": "appliance", "appliance_id": "washer"},
        calls=[
            ("safety_check", {"danger_reported": False}),
            ("identify_appliance", {"appliance_type": "washer"}),
        ],
        say="Is this your Kelvara washer in the laundry closet?",
    ),
    Turn(
        "Yes, that's the one.",
        tools=["find_manual"],
        state="QUICK_CHECKS",
        calls=[("find_manual", {})],
        say="Is the door closed and the hose clear?",
    ),
    Turn(
        "The door is closed and the hose is fine. It says E31.",
        tools=["diagnose"],
        state="PREPARE",
        card={"type": "diagnosis", "error_code": "E31"},
        check=_page(24),
        calls=[("diagnose", {"error_code": "E31"})],
        say="E31 is a drain pump fault. We start with the pump filter, page 24. Ready?",
    ),
    Turn(
        "Okay, ready.",
        tools=["next_step"],
        state="STEPS",
        card=STEP_1,
        calls=[("next_step", {})],
        say="Step 1 of 8. Turn it off and unplug it.",
    ),
    Turn(
        "It's unplugged.",
        tools=["confirm_gate", "next_step"],
        state="STEPS",
        card={"step_number": 2},
        calls=[("confirm_gate", {"confirmed": True}), ("next_step", {})],
        say="Step 2 of 8. If a hot wash just ran, wait ten minutes.",
    ),
    Turn(
        "I waited and the water is cool.",
        tools=["confirm_gate", "next_step"],
        state="STEPS",
        args=[("confirm_gate", {"confirmed": True})],
        card={"step_number": 3},
        calls=[("confirm_gate", {"confirmed": True}), ("next_step", {})],
        say="Step 3 of 8. Open the small panel at the bottom right.",
    ),
    *[
        Turn(
            "Next.",
            tools=["next_step"],
            state="STEPS",
            card={"step_number": n},
            calls=[("next_step", {})],
            say=f"Step {n} of 8.",
        )
        for n in (4, 5, 6, 7, 8)
    ],
    Turn(
        "Done, it ran the cycle.",
        # "It ran" is not "it worked". Either call lands in VERIFY: the engine refuses to record
        # "fixed" until the user has been asked.
        any_of=[["next_step"], ["report_result"]],
        state="VERIFY",
        card={"type": "verify"},
        calls=[("next_step", {})],
        say="Did the error go away?",
    ),
    Turn(
        "It still says E31.",
        tools=["report_result"],
        state="HANDOFF",
        args=[("report_result", {"outcome": "not_fixed"})],
        card={"type": "handoff"},
        forbid=["next_step"],
        calls=[("report_result", {"outcome": "not_fixed"})],
        say="This one needs a technician, and that's okay. Want me to write your landlord?",
    ),
    Turn(
        "Yes, please write to my landlord.",
        tools=["draft_landlord_message"],
        state="HANDOFF",
        card={"type": "landlord_message", "language": "en"},
        check=_landlord,
        calls=[("draft_landlord_message", {})],
        say="I've drafted a message to Lakeview Property Management. It's on your screen.",
    ),
]

# --- Scenario C (negative): danger -------------------------------------------------------------

SCENARIO_C = [
    Turn(
        "I smell burning from the dishwasher.",
        tools=["start_repair"],
        state={"SAFETY_RECHECK", "STOPPED"},
        forbid=["identify_appliance", "find_manual", "quick_checks", "diagnose", "next_step"],
        calls=[
            ("start_repair", {"member_id": "priya", "description": "I smell burning"}),
            ("safety_check", {"danger_reported": True, "details": "I smell burning"}),
        ],
        say="Please stop. If it's safe, unplug it, and call a professional.",
    ),
]
# If the model asks before stopping, this follow-up makes it explicit (live runs only).
SCENARIO_C_CONFIRM = Turn(
    "Yes, I smell burning right now.",
    tools=["safety_check"],
    state="STOPPED",
    args=[("safety_check", {"danger_reported": True})],
    card={"type": "safety_stop"},
    forbid=["identify_appliance", "find_manual", "quick_checks", "diagnose", "next_step"],
)

# --- Danger answers (live): explicit booleans in English and Spanish ---------------------------

DANGER_SETUP = Turn("My dishwasher is beeping.", tools=["start_repair"], state="SAFETY_CHECK")

DANGER_ANSWERS = [
    ("Yes, I smell burning.", "priya", None, True),
    ("Sí, huele a quemado.", "lucia", "es", True),
    ("No, I don't smell anything.", "priya", None, False),
    ("No, no huele a nada.", "lucia", "es", False),
]

# --- Scripted-model plans for the plumbing tests -------------------------------------------------


def expand_scripted(turns: list[Turn]) -> list[Turn]:
    """Write out the repeating turns for the scripted model, which replays a fixed script."""
    out: list[Turn] = []
    for turn in turns:
        out.extend([turn] * (turn.scripted_repeats if turn.repeat_until else 1))
    return out


def play(bridge, turns: list[Turn], *, live: bool, report=None) -> list[dict[str, Any]]:
    """Run the turns. Live runs honor `repeat_until`; scripted runs get turns already expanded."""
    responses: list[dict[str, Any]] = []
    last_card: dict[str, Any] | None = None
    for turn in turns:
        tries = turn.max_repeats if (live and turn.repeat_until) else 1
        for _ in range(tries):
            resp = bridge.turn(turn.text, turn.member, turn.language)
            if report:
                report(len(responses) + 1, turn, resp)
            verify(resp, turn)
            responses.append(resp)
            if resp["card"] is not None:
                last_card = resp["card"]
            if not (live and turn.repeat_until) or turn.repeat_until(resp, last_card):
                break
        else:
            raise AssertionError(f"{turn.text!r}: the repeat condition never came true")
    return responses


def plans(turns: list[Turn]):
    from .fakes import Plan

    return [Plan(calls=t.calls, say=t.say) for t in turns]
