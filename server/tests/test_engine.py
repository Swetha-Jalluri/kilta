import json

import pytest

from kilta.data import DataStore
from kilta.engine import Engine
from kilta.models import State
from tests.conftest import TODAY, edit_json, to_prepare, to_quick_checks

GUARDED_ACTIONS = [
    "identify_appliance",
    "find_manual",
    "quick_checks",
    "diagnose",
    "next_step",
    "confirm_gate",
    "pause_repair",
    "resume_repair",
    "go_back",
    "report_result",
]


def call(engine: Engine, action: str, sid: str):
    if action == "report_result":
        return engine.report_result(sid, fixed=True)
    if action == "diagnose":
        return engine.diagnose(sid, error_code="E24")
    return getattr(engine, action)(sid)


def walk_to_verify(engine: Engine, sid: str) -> None:
    """Advance through the steps, confirming every gate, until the verify prompt."""
    while True:
        out = engine.next_step(sid)
        if out.refused:
            assert out.reason == "gate_unconfirmed"
            engine.confirm_gate(sid)
            continue
        if out.session.state == State.VERIFY:
            return


# --- safety first -------------------------------------------------------------------------


@pytest.mark.parametrize("action", GUARDED_ACTIONS)
def test_nothing_runs_before_the_safety_check(engine, action):
    sid = engine.start_repair("priya", "my dishwasher is beeping").session.id
    out = call(engine, action, sid)
    assert out.refused and out.reason == "safety_first"
    assert out.card["type"] == "safety_question"
    assert out.session.state == State.SAFETY_CHECK


def test_safety_clear_unlocks_identification(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    out = engine.safety_check(sid, danger_reported=False)
    assert out.session.state == State.IDENTIFY and not out.refused


@pytest.mark.parametrize(
    "description",
    [
        "I smell burning from the dishwasher",
        "there was a spark",
        "smoke is coming out",
        "no, I don't smell any burning",
    ],
)
def test_danger_words_in_the_description_ask_for_an_explicit_safety_answer(engine, description):
    out = engine.start_repair("priya", description)
    assert out.session.state == State.SAFETY_RECHECK
    assert out.card["type"] == "safety_recheck"
    refused = engine.next_step(out.session.id)
    assert refused.refused and refused.reason == "safety_recheck"
    assert engine.identify_appliance(out.session.id, appliance_id="dishwasher").refused


def test_only_an_explicit_true_answer_stops_after_a_recheck(engine):
    sid = engine.start_repair("priya", "I smell burning from the dishwasher").session.id
    out = engine.safety_check(sid, danger_reported=True, details="yes, burning right now")
    assert out.session.state == State.STOPPED and out.card["type"] == "safety_stop"


def test_an_explicit_false_answer_clears_the_recheck_even_with_danger_words(engine):
    sid = engine.start_repair("priya", "my dishwasher smells like burning plastic").session.id
    out = engine.safety_check(sid, danger_reported=False, details="no, I don't smell any burning")
    # the dishwasher was named in the description, so it is confirmed straight away
    assert out.session.state == State.MANUAL and out.session.safety_cleared
    assert not out.refused and out.session.recheck_from is None


def test_recheck_mid_repair_returns_to_where_it_was(engine):
    sid = to_quick_checks(engine)
    recheck = engine.diagnose(sid, error_code="E24", symptoms="it was sparking earlier")
    assert recheck.session.state == State.SAFETY_RECHECK
    assert engine.diagnose(sid, error_code="E24").reason == "safety_recheck"
    back = engine.safety_check(sid, danger_reported=False, details="no, nothing sparking now")
    assert back.session.state == State.QUICK_CHECKS and not back.refused
    assert engine.diagnose(sid, error_code="E24").session.state == State.PREPARE


def test_danger_reported_stops_and_blocks_every_action(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    out = engine.safety_check(sid, danger_reported=True, details="smells like burning")
    assert out.session.state == State.STOPPED
    assert "emergency" in out.say.lower() or "professional" in out.say.lower()
    for action in GUARDED_ACTIONS:
        refused = call(engine, action, sid)
        assert refused.refused and refused.reason == "stopped", action
    assert engine.safety_check(sid, danger_reported=False).session.state == State.STOPPED


def test_a_danger_found_mid_repair_stops_it(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    out = engine.safety_check(sid, danger_reported=True, details="now I smell smoke")
    assert out.session.state == State.STOPPED
    assert engine.next_step(sid).reason == "stopped"


def test_a_tampered_session_without_safety_clearance_still_cannot_advance(engine, store):
    sid, _ = to_prepare(engine)
    session = store.load_session(sid)
    session.safety_cleared = False
    store.save_session(session)
    out = engine.next_step(sid)
    assert out.refused and out.reason == "safety_first"


def test_stopped_session_can_give_a_technician_summary_and_landlord_message(engine):
    sid = engine.start_repair("priya", "burning smell from the dishwasher").session.id
    assert engine.create_technician_summary(sid).reason == "safety_recheck"
    engine.safety_check(sid, danger_reported=True)
    assert engine.create_technician_summary(sid).card["type"] == "technician_summary"
    assert "Lakeview" in engine.draft_landlord_message(sid).card["to"]


# --- order of the flow --------------------------------------------------------------------


def test_finding_the_manual_brings_the_quick_checks_with_it(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    engine.safety_check(sid)
    engine.identify_appliance(sid, appliance_type="dishwasher")
    out = engine.find_manual(sid)
    assert out.session.state == State.QUICK_CHECKS and out.session.quick_checks_shown
    assert out.card["type"] == "quick_checks" and out.card["page"] == 16
    assert out.card["manual"]["manual_id"] == "kelvara-dw300"
    assert "Door" in out.say or "door" in out.say  # the checks themselves are in the reply
    assert engine.diagnose(sid, error_code="E24").session.state == State.PREPARE


def test_diagnose_still_needs_the_quick_checks_to_have_been_shown(engine, store):
    sid = to_quick_checks(engine)
    session = store.load_session(sid)
    session.quick_checks_shown = False  # e.g. a session saved by an older version
    store.save_session(session)
    out = engine.diagnose(sid, error_code="E24")
    assert out.refused and out.reason == "quick_checks_first"
    assert out.card["type"] == "quick_checks"
    assert engine.diagnose(sid, error_code="E24").session.state == State.PREPARE


def test_next_step_before_diagnosis_is_refused(engine):
    sid = to_quick_checks(engine)
    out = engine.next_step(sid)
    assert out.refused and out.reason == "wrong_state"


def test_identify_by_spoken_model_code(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    engine.safety_check(sid)
    out = engine.identify_appliance(sid, model_code="d w 300 k7s2")
    assert out.session.appliance_id == "dishwasher" and out.session.state == State.MANUAL


def test_identify_asks_when_ambiguous(engine):
    sid = engine.start_repair("priya", "something is broken").session.id
    engine.safety_check(sid)
    out = engine.identify_appliance(sid)
    assert out.session.state == State.IDENTIFY and out.card["type"] == "appliance_list"
    out = engine.identify_appliance(sid, model_code="ZZ-999")
    assert out.session.state == State.IDENTIFY


def test_a_setting_fixing_it_ends_at_fixed(engine):
    sid = to_quick_checks(engine)
    out = engine.quick_checks(sid, setting_fixed=True, note="Child Lock was on")
    assert out.session.state == State.FIXED
    assert engine.store.appliance("dishwasher").past_repairs[-1].fix.startswith("Quick check")


def test_unknown_error_code_asks_again(engine):
    sid = to_quick_checks(engine)
    out = engine.diagnose(sid, error_code="E99")
    assert out.session.state == State.DIAGNOSE and out.card["type"] == "ask_code"
    assert engine.diagnose(sid, error_code="e 24").session.state == State.PREPARE


# --- gates --------------------------------------------------------------------------------


def test_a_gated_step_cannot_advance_without_confirmation(engine):
    sid, _ = to_prepare(engine)
    first = engine.next_step(sid)
    assert first.card["step_number"] == 1 and first.card["gate"]["confirmed"] is False
    for _ in range(3):
        refused = engine.next_step(sid)
        assert refused.refused and refused.reason == "gate_unconfirmed"
        assert refused.session.step_index == 0
        assert "unplugged" in refused.say.lower()
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 2


def test_declining_a_gate_keeps_it_closed(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid, confirmed=False)
    assert engine.next_step(sid).reason == "gate_unconfirmed"


def test_the_second_gate_in_the_filter_procedure_is_enforced(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    for expected in range(2, 7):
        assert engine.next_step(sid).card["step_number"] == expected
    assert engine.next_step(sid).reason == "gate_unconfirmed"  # step 6: power still off?
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 7


def test_going_back_never_skips_a_gate(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    engine.next_step(sid)
    back = engine.go_back(sid)
    assert back.card["step_number"] == 1
    assert engine.go_back(sid).reason == "at_first_step"


def test_you_cannot_report_fixed_before_the_last_step(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    out = engine.report_result(sid, fixed=True)
    assert out.refused and out.reason == "steps_unfinished"


def test_step_cards_carry_labels_gate_and_source_separately(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    for _ in range(5):
        engine.next_step(sid)
    engine.confirm_gate(sid)
    card = engine.next_step(sid).card  # step 7
    assert card["source"] == {"manual_id": "kelvara-dw300", "page": 18}
    last = engine.next_step(sid).card  # step 8
    assert last["panel_labels"] == ["Rinse"] and last["gate"] is None


# --- technician-only ----------------------------------------------------------------------


@pytest.mark.parametrize("code", ["E15", "E09"])
def test_technician_only_codes_route_to_handoff(engine, code):
    sid, out = to_prepare(engine, code)
    assert out.session.state == State.HANDOFF
    assert out.card["type"] == "handoff" and out.card["source"]["page"] == 19
    refused = engine.next_step(sid)
    assert refused.refused and refused.reason == "repair_closed"
    assert engine.store.appliance("dishwasher").past_repairs[-1].outcome == "handed_off"


@pytest.mark.parametrize(
    "symptom", ["I think the refrigerant is leaking", "I want to rewire the board"]
)
def test_technician_only_topics_in_symptoms_route_to_handoff(engine, symptom):
    sid = to_quick_checks(engine)
    out = engine.diagnose(sid, error_code="E24", symptoms=symptom)
    assert out.session.state == State.HANDOFF


# --- pause and resume ---------------------------------------------------------------------


def test_sessions_persist_and_resume_in_a_fresh_process(engine, data_dir):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    engine.next_step(sid)
    engine.next_step(sid)
    engine.pause_repair(sid)
    assert json.loads((data_dir / "sessions" / f"{sid}.json").read_text())["state"] == "PAUSED"

    fresh = Engine(DataStore(data_dir), today=lambda: TODAY)
    state = fresh.get_repair_state()
    assert state.session.id == sid and state.session.state == State.PAUSED
    resumed = fresh.resume_repair()
    assert resumed.session.state == State.STEPS and resumed.card["step_number"] == 3
    assert "stopped at step 3" in resumed.say.lower()


def test_resuming_asks_the_safety_gate_again(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    engine.next_step(sid)
    engine.pause_repair(sid)
    resumed = engine.resume_repair(sid)
    assert resumed.card["gate"] == {
        "prompt": "Is the dishwasher unplugged?",
        "kind": "after",
        "confirmed": False,
    }
    blocked = engine.next_step(sid)
    assert blocked.refused and blocked.reason == "gate_unconfirmed"
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 3


def test_every_state_change_is_written_to_disk(engine, data_dir):
    sid = engine.start_repair("priya", "beeping").session.id
    path = data_dir / "sessions" / f"{sid}.json"
    seen = []
    for action in (
        lambda: engine.safety_check(sid),
        lambda: engine.identify_appliance(sid, appliance_id="dishwasher"),
        lambda: engine.find_manual(sid),
    ):
        action()
        seen.append(json.loads(path.read_text())["state"])
    assert seen == ["IDENTIFY", "MANUAL", "QUICK_CHECKS"]


# --- scenario A: dishwasher E24 fixed at home ---------------------------------------------


def test_scenario_a_end_to_end(engine):
    sid = engine.start_repair("priya", "My dishwasher is beeping").session.id
    # the dishwasher was named in the first message, so the engine confirms it right away
    assert engine.safety_check(sid).session.state == State.MANUAL
    assert engine.identify_appliance(sid, appliance_type="dishwasher").session.state == State.MANUAL
    assert engine.find_manual(sid).session.state == State.QUICK_CHECKS
    qc = engine.quick_checks(sid)
    assert qc.card["page"] == 16 and len(qc.card["checks"]) == 4

    diag = engine.diagnose(sid, error_code="E24")
    assert diag.session.state == State.PREPARE
    assert diag.card["source"]["page"] == 18 and diag.card["minutes"] == 15
    assert diag.card["tools"] == ["towel", "soft brush", "small bowl"]
    assert diag.card["repeat_count"] == 2 and diag.card["last_repair"]["date"] == "2025-11-02"
    assert "second time" in diag.say

    assert engine.next_step(sid).card["step_number"] == 1
    assert engine.next_step(sid).reason == "gate_unconfirmed"
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 2

    engine.pause_repair(sid)
    assert engine.resume_repair(sid).session.state == State.STEPS
    engine.confirm_gate(sid)
    walk_to_verify(engine, sid)
    fixed = engine.report_result(sid, fixed=True)
    assert fixed.session.state == State.FIXED
    assert fixed.card["repeat_count"] == 2
    assert fixed.card["health_card"]["repeat_codes"] == {"E24": 2}
    assert len(fixed.card["health_card"]["repairs"]) == 2
    assert "anonymously" in fixed.say

    declined = engine.share_insight(sid, consent=False)
    assert declined.refused and declined.reason == "consent_required"
    assert engine.store.contributions() == []
    shared = engine.share_insight(sid, consent=True)
    assert not shared.refused
    assert len(engine.store.contributions()) == 1
    engine.share_insight(sid, consent=True)
    assert len(engine.store.contributions()) == 1  # sharing twice does not double count
    assert engine.services.get_insights("DW-300").card["entries"][0]["reports"] == 413


def test_not_fixed_tries_the_next_cause_then_hands_off(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    walk_to_verify(engine, sid)
    second = engine.report_result(sid, fixed=False)
    assert (
        second.session.state == State.PREPARE and second.card["procedure"] == "Check the drain hose"
    )
    engine.next_step(sid)
    engine.confirm_gate(sid)
    walk_to_verify(engine, sid)
    out = engine.report_result(sid, fixed=False)
    assert out.session.state == State.HANDOFF
    assert [a.result for a in out.session.attempts] == ["not_fixed", "not_fixed"]


# --- scenario B: washer E31, renter handoff -----------------------------------------------


def test_scenario_b_washer_e31_landlord_handoff(engine):
    sid, diag = to_prepare(engine, "E31", appliance_id="washer")
    assert diag.card["source"]["page"] == 24
    engine.next_step(sid)
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 2
    assert engine.next_step(sid).reason == "gate_unconfirmed"  # water cool?
    engine.confirm_gate(sid)
    walk_to_verify(engine, sid)

    out = engine.report_result(sid, fixed=False, notes="still says E31")
    assert out.session.state == State.HANDOFF
    assert out.card["source"] == {"manual_id": "kelvara-wm500", "page": 25}
    assert "landlord_message" in out.card["offers"]

    message = engine.draft_landlord_message(sid)
    body = message.card["body"]
    assert message.card["to"] == "Lakeview Property Management"
    for expected in ("WM-500-R4T9", "E31", "pump filter", "page 24", "technician"):
        assert expected in body, expected
    assert body.rstrip().endswith("Priya")

    summary = engine.create_technician_summary(sid).card
    assert summary["model_code"] == "WM-500-R4T9" and summary["tried"][0]["page"] == 24


def test_landlord_message_refused_for_owners(data_dir):
    edit_json(data_dir / "household.json", lambda h: h.update(renter=False))
    engine = Engine(DataStore(data_dir), today=lambda: TODAY)
    sid, _ = to_prepare(engine, "E15")
    out = engine.draft_landlord_message(sid)
    assert out.refused and out.reason == "not_renter"
    assert engine.create_technician_summary(sid).card["type"] == "technician_summary"


def test_handoff_documents_are_refused_mid_repair(engine):
    sid, _ = to_prepare(engine)
    assert engine.create_technician_summary(sid).reason == "not_in_handoff"
    assert engine.draft_landlord_message(sid).reason == "not_in_handoff"


def test_washer_door_lock_escalates_after_closing_it_firmly(engine):
    sid, diag = to_prepare(engine, "dE", appliance_id="washer")
    assert diag.card["procedure"] == "Close the door firmly"
    engine.next_step(sid)
    assert engine.next_step(sid).session.state == State.VERIFY
    out = engine.report_result(sid, fixed=False)
    assert out.session.state == State.HANDOFF and out.card["source"]["page"] == 22


# --- simulated services -------------------------------------------------------------------


def test_orders_need_consent_and_return_appliances_only(engine):
    assert engine.services.lookup_orders(consent=False).reason == "consent_required"
    out = engine.services.lookup_orders(consent=True)
    assert {o["category"] for o in out.card["orders"]} == {"appliance"}


def test_warranty_is_an_estimate_from_the_purchase_date(engine):
    card = engine.services.check_warranty("dishwasher").card
    assert (
        card["ends"] == "2026-03-12" and card["in_warranty"] is False and card["estimate"] is True
    )


def test_parts_cart_needs_explicit_confirmation(engine):
    proposal = engine.services.build_parts_cart("dishwasher", ["KV-DW3-FLT"], confirm=False)
    assert proposal.refused and proposal.card["status"] == "needs_confirmation"
    done = engine.services.build_parts_cart("dishwasher", ["KV-DW3-FLT"], confirm=True)
    assert done.card["status"] == "created" and done.card["simulated"] is True
    assert engine.services.build_parts_cart("dishwasher", ["KV-WM5-PFLT"], confirm=True).refused


def test_search_manual_gives_pages_but_never_steps(engine):
    out = engine.services.search_manual("not draining", appliance_id="dishwasher")
    assert out.card["results"][0]["page"] == 18
    assert "unplug" not in json.dumps(out.card).lower()


def test_unknown_session_and_member_are_handled(engine):
    assert engine.get_repair_state("r-nope").reason == "no_session"
    assert engine.start_repair("nobody", "x").reason == "unknown_member"


# --- review fixes ---------------------------------------------------------------------------


def test_a_safety_stop_is_sticky_for_calls_without_a_session_id(engine):
    older, _ = to_prepare(engine)
    engine.next_step(older)
    newer = engine.start_repair("priya", "I smell gas and smoke").session.id
    out = engine.next_step()  # no session id: the newest session is waiting on a safety answer
    assert out.refused and out.reason == "safety_recheck"
    engine.safety_check(newer, danger_reported=True)
    out = engine.next_step()
    assert out.refused and out.reason == "stopped"
    assert engine.store.load_session(older).state == State.STEPS


def test_danger_words_in_diagnose_symptoms_ask_for_a_safety_answer(engine):
    sid = to_quick_checks(engine)
    out = engine.diagnose(sid, error_code="E24", symptoms="it is sparking and smells burnt")
    assert out.session.state == State.SAFETY_RECHECK
    assert engine.safety_check(sid, danger_reported=True).session.state == State.STOPPED


def test_danger_words_in_quick_check_note_ask_for_a_safety_answer(engine):
    sid = to_quick_checks(engine)
    out = engine.quick_checks(sid, setting_fixed=False, note="there was a spark")
    assert out.session.state == State.SAFETY_RECHECK


def test_danger_words_in_result_notes_ask_for_a_safety_answer(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    walk_to_verify(engine, sid)
    out = engine.report_result(sid, fixed=True, notes="it works but I smell burning")
    assert out.session.state == State.SAFETY_RECHECK
    assert engine.store.appliance("dishwasher").past_repairs[-1].outcome == "fixed"  # seeded only
    back = engine.safety_check(sid, danger_reported=False)
    assert back.session.state == State.VERIFY


def test_a_wrong_appliance_can_be_corrected_before_the_manual_is_confirmed(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    engine.safety_check(sid)
    engine.identify_appliance(sid, appliance_type="washer")
    out = engine.identify_appliance(sid, appliance_type="dishwasher")
    assert out.session.appliance_id == "dishwasher" and out.session.state == State.MANUAL


# --- gate kinds: "after" tells the step first, "before" withholds it ------------------------

SUMP_TEXT = "Check the sump opening for debris"


def to_dw_step_six(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    for _ in range(4):
        engine.next_step(sid)
    return sid, engine.next_step(sid)  # step 6


def test_gate_kinds_in_the_manuals():
    from kilta.data import DataStore

    store = DataStore()
    dw = store.manuals["kelvara-dw300"]
    kinds = {(p.id, s.id): s.gate.kind for p in dw.procedures for s in p.steps if s.gate}
    assert kinds == {
        ("clean-filter", "unplug"): "after",
        ("clean-filter", "check-sump"): "before",
        ("check-drain-hose", "unplug"): "after",
    }
    wm = store.manuals["kelvara-wm500"]
    assert {(p.id, s.id): s.gate.kind for p in wm.procedures for s in p.steps if s.gate} == {
        ("clean-pump-filter", "unplug"): "after",
        ("clean-pump-filter", "cool-down"): "after",
    }


def test_an_after_gate_tells_the_step_first(engine):
    sid, _ = to_prepare(engine)
    out = engine.next_step(sid)
    assert "unplug" in out.say.lower() and out.card["text"].startswith("Turn off")
    assert out.card["gate"]["kind"] == "after" and out.card["text_withheld"] is False


def test_a_before_gate_never_returns_the_step_text_until_confirmed(engine):
    sid, step6 = to_dw_step_six(engine)
    assert step6.card["step_number"] == 6 and step6.card["text_withheld"] is True
    assert step6.card["step_id"] is None  # "check-sump" would hint at the hidden step
    assert step6.card["gate"] == {
        "prompt": "Is the power still off?",
        "kind": "before",
        "confirmed": False,
    }

    def leaked(out) -> bool:
        blob = json.dumps({"say": out.say, "card": out.card}).lower()
        return "sump opening" in blob or "by hand" in blob or "debris" in blob

    # Every way of asking for the step, before confirming.
    attempts = [
        step6,
        engine.next_step(sid),  # refused
        engine.next_step(sid, repeat=True),
        engine.get_repair_state(sid),
        engine.confirm_gate(sid, confirmed=False),
        engine.report_result(sid, fixed=True),  # refused: not at the last step
    ]
    assert attempts[1].reason == "gate_unconfirmed" and attempts[1].card["text"] is None
    for out in attempts:
        assert not leaked(out), out.say
    paused = engine.pause_repair(sid)
    assert not leaked(paused)
    resumed = engine.resume_repair(sid)
    assert not leaked(resumed) and resumed.card["text_withheld"] is True
    # The unplug gate is asked again after a resume, and the sump text stays hidden meanwhile.
    assert resumed.card["gate"]["prompt"] == "Is the dishwasher unplugged?"
    again = engine.confirm_gate(sid)
    assert again.card["text_withheld"] is True and not leaked(again)
    assert engine.next_step(sid).reason == "gate_unconfirmed"
    revealed = engine.confirm_gate(sid)
    assert SUMP_TEXT in revealed.say and revealed.card["text"].startswith(SUMP_TEXT)
    assert revealed.card["text_withheld"] is False and revealed.card["step_id"] == "check-sump"
    assert engine.get_repair_state(sid).card["text"].startswith(SUMP_TEXT)
    assert engine.next_step(sid).card["step_number"] == 7


def test_resuming_on_a_before_gated_step_withholds_the_text_again(engine):
    sid, _ = to_dw_step_six(engine)
    engine.confirm_gate(sid)
    engine.pause_repair(sid)
    resumed = engine.resume_repair(sid)
    assert resumed.card["text"] is None and resumed.card["gate"]["confirmed"] is False
    assert SUMP_TEXT not in json.dumps(resumed.card) + resumed.say


def test_a_tool_result_over_the_wire_also_withholds_a_before_gate_step(engine):
    sid, step6 = to_dw_step_six(engine)
    structured = step6.structured()
    assert structured["card"]["text"] is None
    assert SUMP_TEXT not in json.dumps(structured) + step6.say
    assert "by hand" not in json.dumps(structured).lower()


# --- reset keeps the seeded history ---------------------------------------------------------


def test_reset_keeps_the_seeded_past_repair_for_repeat_detection(data_dir):
    import shutil
    import subprocess

    if shutil.which("make") is None:
        pytest.skip("make not installed")
    from tests.conftest import REPO_DATA

    engine = Engine(DataStore(data_dir), today=lambda: TODAY)
    sid, diag = to_prepare(engine)
    assert diag.card["repeat_count"] == 2
    engine.next_step(sid)
    engine.confirm_gate(sid)
    walk_to_verify(engine, sid)
    engine.report_result(sid, fixed=True)
    assert len(engine.store.appliance("dishwasher").past_repairs) == 2
    assert (data_dir / "state").exists() and (data_dir / "sessions").exists()

    subprocess.run(
        ["make", "-C", str(REPO_DATA.parent), "reset", f"DATA_DIR={data_dir}"],
        check=True,
        capture_output=True,
    )
    assert not (data_dir / "state").exists() and not (data_dir / "sessions").exists()

    fresh = Engine(DataStore(data_dir), today=lambda: TODAY)
    history = fresh.store.appliance("dishwasher").past_repairs
    assert [(r.date.isoformat(), r.error_code, r.outcome) for r in history] == [
        ("2025-11-02", "E24", "fixed")
    ]
    sid, diag = to_prepare(fresh)
    assert diag.card["repeat_count"] == 2 and "second time" in diag.say
    assert diag.card["last_repair"]["date"] == "2025-11-02"


# --- second review ----------------------------------------------------------------------------


def test_not_fixed_after_pause_and_resume_does_not_wedge_the_next_procedure(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    for _ in range(5):
        engine.next_step(sid)
    engine.confirm_gate(sid)  # step 6, before-gate
    engine.pause_repair(sid)
    engine.resume_repair(sid)
    assert engine.store.load_session(sid).reconfirm_gate == "clean-filter:check-sump"
    out = engine.report_result(sid, fixed=False)
    assert out.session.state == State.PREPARE and out.session.reconfirm_gate is None
    first = engine.next_step(sid)
    assert first.card["procedure_id"] == "check-drain-hose" and first.card["step_number"] == 1
    assert engine.next_step(sid).reason == "gate_unconfirmed"
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 2


def test_a_stale_reconfirm_key_is_ignored_not_fatal(engine, store):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    session = store.load_session(sid)
    session.reconfirm_gate = "some-other-procedure:gone"
    store.save_session(session)
    out = engine.next_step(sid)
    assert out.refused and out.reason == "gate_unconfirmed"  # the real unplug gate
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 2  # not wedged


def test_danger_words_in_symptoms_are_caught_before_the_quick_checks_refusal(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    engine.safety_check(sid, danger_reported=False)
    engine.identify_appliance(sid, appliance_type="dishwasher")
    engine.find_manual(sid)
    out = engine.diagnose(sid, error_code="E24", symptoms="I smell gas")
    assert out.session.state == State.SAFETY_RECHECK and out.reason is None
    back = engine.safety_check(sid, danger_reported=False)
    assert back.session.state == State.QUICK_CHECKS


@pytest.mark.parametrize("text", ["it sparked", "smells burned", "it's smoky", "I got zapped"])
def test_more_danger_word_forms_trigger_a_recheck(engine, text):
    assert engine.start_repair("priya", text).session.state == State.SAFETY_RECHECK


# --- danger mentions, carried stops, resume after a before-gate -------------------------------


def test_danger_words_with_a_no_danger_answer_are_logged_not_asked_twice(engine):
    sid = engine.start_repair("priya", "it smells like burning plastic").session.id
    out = engine.safety_check(sid, danger_reported=False, details="no, I don't smell any burning")
    assert out.session.state == State.IDENTIFY  # one answer is enough
    assert out.session.danger_mentions == ["burning"]  # the recheck text too, deduplicated

    engine.identify_appliance(sid, appliance_id="dishwasher")
    engine.find_manual(sid)
    engine.quick_checks(sid)
    mid = engine.safety_check(sid, danger_reported=False, details="now I smell smoke")
    assert mid.session.state == State.QUICK_CHECKS and not mid.refused
    assert mid.session.danger_mentions == ["burning", "smoke"]

    engine.diagnose(sid, error_code="E15")
    summary = engine.create_technician_summary(sid).card
    assert summary["danger_mentions"] == ["burning", "smoke"]
    assert (
        "burning, smoke" in summary["safety_notes"]
        or "burning and smoke" in summary["safety_notes"]
    )
    assert "nothing dangerous was happening" in summary["safety_notes"]


def stopped_dishwasher_session(engine, store):
    sid = engine.start_repair("priya", "I smell burning from the dishwasher").session.id
    engine.safety_check(sid, danger_reported=False)  # first, an honest "no"...
    engine.identify_appliance(sid, appliance_id="dishwasher")
    engine.safety_check(sid, danger_reported=True, details="burning smell again")
    assert store.load_session(sid).state == State.STOPPED
    return sid


def test_a_new_repair_after_a_stop_carries_the_safety_note(engine, store):
    old = stopped_dishwasher_session(engine, store)
    out = engine.start_repair("priya", "the dishwasher is beeping")
    assert not out.refused and out.session.state == State.SAFETY_CHECK
    assert out.card["prior_stop"]["session_id"] == old
    assert "Earlier you reported burning with your Kelvara DW-300 dishwasher" in out.say
    assert "Has a professional checked it since?" in out.say
    assert out.say.endswith(store.safety["safety_question"])
    # Still the normal flow afterwards, and the guard repeats the same question.
    assert "Earlier you reported" in engine.next_step(out.session.id).say
    assert engine.safety_check(out.session.id, danger_reported=False).session.state == (
        State.MANUAL  # "the dishwasher is beeping" already named the appliance
    )


def test_a_stop_is_carried_when_the_appliance_is_not_named(engine, store):
    stopped_dishwasher_session(engine, store)
    out = engine.start_repair("lucia", "it is beeping again")
    assert "Earlier you reported burning" in out.say


def test_a_stop_is_not_carried_to_a_different_appliance(engine, store):
    stopped_dishwasher_session(engine, store)
    out = engine.start_repair("priya", "my washer shows E31")
    assert out.session.prior_stop is None and "Earlier" not in out.say
    # "dishwasher" must not be mistaken for "washer"
    again = engine.start_repair("priya", "the dishwasher shows E24")
    assert again.session.prior_stop is None  # newest session is the washer one, not a stop


def test_only_a_stopped_session_is_carried(engine):
    sid, _ = to_prepare(engine)
    out = engine.start_repair("priya", "something else is beeping")
    assert out.session.prior_stop is None and sid != out.session.id


def test_resuming_right_after_a_before_gated_step_asks_its_gate_again(engine):
    sid, _ = to_prepare(engine)
    engine.next_step(sid)
    engine.confirm_gate(sid)
    for _ in range(4):
        engine.next_step(sid)
    engine.next_step(sid)  # step 6, withheld
    revealed = engine.confirm_gate(sid)
    assert SUMP_TEXT in revealed.say
    step7 = engine.next_step(sid)
    assert step7.card["step_number"] == 7 and step7.card["text_withheld"] is False
    engine.pause_repair(sid)

    resumed = engine.resume_repair(sid)
    assert resumed.card["step_number"] == 7
    assert resumed.card["gate"] == {
        "prompt": "Is the power still off?",
        "kind": "before",
        "confirmed": False,
    }
    assert resumed.card["text"].startswith("Put the filter back")  # step 7 itself is not hidden
    assert SUMP_TEXT not in resumed.say + json.dumps(resumed.card)  # step 6 is not replayed
    blocked = engine.next_step(sid)
    assert blocked.refused and blocked.reason == "gate_unconfirmed"
    assert blocked.card["step_number"] == 7
    engine.confirm_gate(sid)
    assert engine.next_step(sid).card["step_number"] == 8


# --- the appliance the user already named ----------------------------------------------------


@pytest.mark.parametrize(
    "description, hint",
    [
        ("my washer says E31", "washer"),
        ("The dishwasher is beeping", "dishwasher"),
        ("the washing machine will not drain", "washer"),
        ("both the dishwasher and the washer are acting up", None),
        ("something is beeping", None),
    ],
)
def test_an_appliance_named_in_the_description_is_remembered(engine, description, hint):
    assert engine.start_repair("priya", description).session.appliance_hint == hint


def test_clearing_the_safety_check_confirms_the_appliance_the_user_named(engine):
    sid = engine.start_repair("priya", "my washer says E31").session.id
    out = engine.safety_check(sid, danger_reported=False)
    assert out.session.state == State.MANUAL and out.session.appliance_id == "washer"
    assert out.card["type"] == "appliance" and "Kelvara WM-500" in out.say
    assert out.say.startswith("Good, thank you.") and "Is that the one?" in out.say


def test_without_a_named_appliance_the_safety_check_still_asks_which_one(engine):
    sid = engine.start_repair("priya", "something is beeping").session.id
    out = engine.safety_check(sid, danger_reported=False)
    assert out.session.state == State.IDENTIFY and out.card["type"] == "appliance_list"


def test_the_named_appliance_also_survives_a_safety_recheck(engine):
    sid = engine.start_repair("priya", "my dishwasher smells like burning plastic").session.id
    assert engine.get_repair_state(sid).session.state == State.SAFETY_RECHECK
    out = engine.safety_check(sid, danger_reported=False, details="no, nothing is burning")
    assert out.session.state == State.MANUAL and out.session.appliance_id == "dishwasher"


def test_the_user_can_still_correct_a_wrongly_guessed_appliance(engine):
    sid = engine.start_repair("priya", "the washer is loud").session.id
    engine.safety_check(sid, danger_reported=False)
    out = engine.identify_appliance(sid, appliance_type="dishwasher")
    assert out.session.appliance_id == "dishwasher" and out.session.state == State.MANUAL


def test_asking_to_identify_again_with_nothing_new_keeps_the_identified_appliance(engine):
    sid = engine.start_repair("priya", "my washer says E31").session.id
    engine.safety_check(sid, danger_reported=False)  # confirms the washer by itself
    again = engine.identify_appliance(sid)
    assert again.session.state == State.MANUAL and again.session.appliance_id == "washer"
    assert again.card["type"] == "appliance" and not again.refused


def test_a_wrong_appliance_id_next_to_a_right_model_code_still_identifies(engine):
    sid = engine.start_repair("priya", "something is beeping").session.id
    engine.safety_check(sid, danger_reported=False)
    out = engine.identify_appliance(
        sid, appliance_id="kelvara-wm500x", model_code="WM-500-R4T9", appliance_type="washer"
    )
    assert out.session.appliance_id == "washer"


def test_the_manual_id_works_as_an_appliance_id(engine):
    sid = engine.start_repair("priya", "something is beeping").session.id
    engine.safety_check(sid, danger_reported=False)
    assert engine.identify_appliance(sid, appliance_id="kelvara-wm500").session.appliance_id == (
        "washer"
    )
