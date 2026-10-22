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
    ],
)
def test_danger_in_the_description_stops_the_repair_at_once(engine, description):
    out = engine.start_repair("priya", description)
    assert out.session.state == State.STOPPED
    assert out.card["type"] == "safety_stop"


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
    out = engine.safety_check(sid, danger_reported=False, details="now I smell smoke")
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
    assert engine.create_technician_summary(sid).card["type"] == "technician_summary"
    assert "Lakeview" in engine.draft_landlord_message(sid).card["to"]


# --- order of the flow --------------------------------------------------------------------


def test_diagnose_needs_the_quick_checks_first(engine):
    sid = engine.start_repair("priya", "beeping").session.id
    engine.safety_check(sid)
    engine.identify_appliance(sid, appliance_type="dishwasher")
    engine.find_manual(sid)
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
    assert resumed.card["gate"] == {"prompt": "Is the dishwasher unplugged?", "confirmed": False}
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
    assert engine.safety_check(sid).session.state == State.IDENTIFY
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
