"""The repair engine: a deterministic, safety-gated state machine.

The language model only phrases things. Every rule that matters (safety first, gates,
technician-only routing, grounding in the manual) is enforced here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from .data import DataStore
from .models import (
    Appliance,
    Attempt,
    Manual,
    Outcome,
    PastRepair,
    Procedure,
    Session,
    Source,
    State,
    normalize_code,
)
from .services import Services, ordinal, prior_occurrences

TYPE_ALIASES = {
    "washing machine": "washer",
    "clothes washer": "washer",
    "dish washer": "dishwasher",
}


def _words(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _gate_key(proc: Procedure, step_id: str) -> str:
    return f"{proc.id}:{step_id}"


class Engine:
    def __init__(self, store: DataStore, today: Callable[[], date] = date.today) -> None:
        self.store = store
        self.today = today
        self.services = Services(store, today)

    # --- plumbing ----------------------------------------------------------------------

    def _out(
        self,
        s: Session | None,
        say: str,
        card: dict[str, Any],
        *,
        refused: bool = False,
        reason: str | None = None,
    ) -> Outcome:
        return Outcome(say=say, card=card, session=s, refused=refused, reason=reason)

    def _refuse(self, o: Outcome, reason: str, prefix: str = "") -> Outcome:
        return o.model_copy(update={"refused": True, "reason": reason, "say": f"{prefix}{o.say}"})

    def _save(self, s: Session, note: str | None = None) -> None:
        if note:
            s.log.append(note)
        self.store.save_session(s)

    def _resolve(self, session_id: str | None) -> tuple[Session | None, Outcome | None]:
        # No id means the newest session, even a finished one, so a safety stop is never skipped.
        s = self.store.load_session(session_id) if session_id else self.store.latest_session()
        if s:
            return s, None
        return None, self._out(
            None,
            "We haven't started a repair yet. What's going on with your appliance?",
            {"type": "no_session"},
            refused=True,
            reason="no_session",
        )

    def _appliance(self, s: Session) -> Appliance | None:
        return self.store.appliance(s.appliance_id) if s.appliance_id else None

    def _manual(self, s: Session) -> Manual | None:
        return self.store.manuals.get(s.manual_id) if s.manual_id else None

    def _procedure(self, s: Session) -> Procedure | None:
        manual, pid = self._manual(s), s.procedure_id
        return manual.procedure(pid) if manual and pid else None

    def _guard(self, s: Session, allowed: set[State]) -> Outcome | None:
        """Safety comes first, for every action except safety_check itself."""
        if s.state == State.STOPPED:
            return self._refuse(self._stopped(s), "stopped")
        if s.state == State.SAFETY_RECHECK:
            return self._refuse(self._recheck_question(s), "safety_recheck")
        if s.state == State.SAFETY_CHECK or not s.safety_cleared:
            return self._refuse(self._safety_question(s), "safety_first")
        if s.state in allowed:
            return None
        if s.state in (State.FIXED, State.HANDOFF):
            return self._refuse(
                self._out(
                    s,
                    "This repair is already wrapped up. Want to start a new one?",
                    {"type": "closed", "state": s.state.value},
                ),
                "repair_closed",
            )
        return self._refuse(self.present(s), "wrong_state", "We're not there yet. ")

    # --- presenting the current state ----------------------------------------------------

    def present(self, s: Session) -> Outcome:
        match s.state:
            case State.SAFETY_CHECK:
                return self._safety_question(s)
            case State.SAFETY_RECHECK:
                return self._recheck_question(s)
            case State.STOPPED:
                return self._stopped(s)
            case State.IDENTIFY:
                return self._ask_appliance(s)
            case State.MANUAL:
                a = self._appliance(s)
                name = a.name if a else "that appliance"
                return self._out(
                    s,
                    f"I have your {name}. Shall I pull up its manual?",
                    {"type": "appliance", "appliance_id": s.appliance_id},
                )
            case State.QUICK_CHECKS:
                return self._quick_checks_card(s)
            case State.DIAGNOSE:
                return self._ask_code(s)
            case State.PREPARE:
                return self._prepare(s)
            case State.STEPS:
                return self._step(s)
            case State.PAUSED:
                return self._paused(s)
            case State.VERIFY:
                return self._verify(s)
            case State.FIXED:
                return self._fixed(s)
            case State.HANDOFF:
                return self._handoff(s)
        raise AssertionError(s.state)

    def _safety_question(self, s: Session) -> Outcome:
        q = self.store.safety["safety_question"]
        card: dict[str, Any] = {"type": "safety_question", "question": q}
        if s.prior_stop:
            what = _words(s.prior_stop["words"]) or "a safety problem"
            about = f" with your {s.prior_stop['appliance']}" if s.prior_stop["appliance"] else ""
            follow_up = f"Earlier you reported {what}{about}. Has a professional checked it since?"
            q = f"{follow_up} {q}"
            card.update(question=q, prior_stop=s.prior_stop)
        return self._out(s, q, card)

    def _recheck_question(self, s: Session) -> Outcome:
        say = (
            "You mentioned something that could be unsafe. Before anything else: is that "
            "happening right now, burning, gas, smoke, sparks or a shock? Please answer yes or no."
        )
        return self._out(
            s, say, {"type": "safety_recheck", "question": say, "heard": s.recheck_text}
        )

    def _enter_recheck(self, s: Session, text: str) -> Outcome:
        """Danger words in free text pause the repair. Only an explicit safety_check(true)
        stops it for good; an explicit false carries on where we were."""
        s.recheck_from, s.recheck_text = s.state, text
        s.state = State.SAFETY_RECHECK
        self._save(s, "safety recheck requested")
        return self._recheck_question(s)

    def _stopped(self, s: Session) -> Outcome:
        steps = self.store.safety["stop_instructions"]
        return self._out(
            s,
            "I'm stopping here, because safety comes first. " + " ".join(steps),
            {"type": "safety_stop", "instructions": steps, "details": s.safety_notes},
        )

    def _ask_appliance(self, s: Session) -> Outcome:
        items = [{"id": a.id, "name": a.name, "room": a.room} for a in self.store.appliances()]
        say = (
            "Which appliance is it? I know about "
            + _words([a.name for a in self.store.appliances()])
            + "."
        )
        return self._out(s, say, {"type": "appliance_list", "appliances": items})

    def _quick_checks_card(self, s: Session) -> Outcome:
        manual = self._manual(s)
        assert manual
        checks = [c.model_dump() for c in manual.quick_checks]
        page = manual.quick_checks[0].source.page
        say = (
            f"Let's try the simple things first, from page {page}. "
            + " ".join(f"{i}. {c.text}" for i, c in enumerate(manual.quick_checks, 1))
            + " Tell me what you find, and what the screen says."
        )
        s.quick_checks_shown = True
        self._save(s)
        return self._out(
            s, say, {"type": "quick_checks", "manual_id": manual.id, "page": page, "checks": checks}
        )

    def _ask_code(self, s: Session, entered: str | None = None) -> Outcome:
        manual = self._manual(s)
        assert manual
        codes = [{"code": c.code, "meaning": c.meaning, "page": c.page} for c in manual.error_codes]
        if entered:
            say = (
                f"I don't see {entered} in this manual. Could you read the code again, one "
                "character at a time?"
            )
        else:
            say = (
                "What does the screen show? If it's a code, read it to me one character at a time."
            )
        return self._out(s, say, {"type": "ask_code", "entered": entered, "known_codes": codes})

    def _prepare(self, s: Session) -> Outcome:
        manual, proc = self._manual(s), self._procedure(s)
        assert manual and proc
        code = manual.error_code(s.error_code or "")
        tools = f"you'll need {_words(proc.tools)}" if proc.tools else "you won't need any tools"
        cause = ""
        if code and s.procedure_index == 0:
            say = f"{code.code} means {code.meaning.lower()}. "
            if code.causes:
                cause = f"The most likely cause is: {code.causes[0].lower()}. "
            lead = say + cause
        else:
            lead = "Okay, let's try the next most likely cause. "
        repeat = ""
        if s.repeat_count > 1:
            repeat = (
                f"This is the {ordinal(s.repeat_count)} time this code has shown up on this one. "
            )
        say = (
            f"{lead}{repeat}It's the {proc.title.lower()} fix, page {proc.source.page}. "
            f"It takes about "
            f"{proc.minutes} minutes and {tools}. Ready to start?"
        )
        card = {
            "type": "diagnosis",
            "error_code": s.error_code,
            "meaning": code.meaning if code else None,
            "causes": code.causes if code else [],
            "procedure_id": proc.id,
            "procedure": proc.title,
            "minutes": proc.minutes,
            "tools": proc.tools,
            "steps": len(proc.steps),
            "procedure_number": s.procedure_index + 1,
            "procedure_total": len(s.procedure_queue),
            "repeat_count": s.repeat_count,
            "source": proc.source.model_dump(),
        }
        return self._out(s, say, card)

    def _pending_gate(self, s: Session) -> tuple[str, str, str] | None:
        """(key, prompt, kind) of the gate that must be confirmed before anything moves on.
        Gates asked again after a resume come first: they belong to earlier steps."""
        proc = self._procedure(s)
        if not proc:
            return None
        proc_id, _, step_id = (s.reconfirm_gate or "").partition(":")
        step = next((st for st in proc.steps if st.id == step_id), None)
        if proc_id == proc.id and step and step.gate:
            assert s.reconfirm_gate
            return s.reconfirm_gate, step.gate.prompt, step.gate.kind
        s.reconfirm_gate = None  # stale: it belonged to another procedure
        if s.step_index >= 0:
            step = proc.steps[s.step_index]
            key = _gate_key(proc, step.id)
            if step.gate and key not in s.confirmed_gates:
                return key, step.gate.prompt, step.gate.kind
        return None

    def _text_withheld(self, s: Session) -> bool:
        """True while the current step sits behind a "before" gate that is not yet confirmed."""
        proc = self._procedure(s)
        if not proc or s.step_index < 0:
            return False
        step = proc.steps[s.step_index]
        gate = step.gate
        return bool(
            gate
            and gate.kind == "before"
            and (_gate_key(proc, step.id) not in s.confirmed_gates or s.reconfirm_gate)
        )

    def _step(self, s: Session, *, blocked: bool = False, lead: str = "") -> Outcome:
        proc = self._procedure(s)
        assert proc and 0 <= s.step_index < len(proc.steps)
        step = proc.steps[s.step_index]
        pending = self._pending_gate(s)
        gate = None
        if step.gate:
            gate = {
                "prompt": step.gate.prompt,
                "kind": step.gate.kind,
                "confirmed": _gate_key(proc, step.id) in s.confirmed_gates,
            }
        if pending and (not step.gate or not gate or not gate["confirmed"]):
            gate = {"prompt": pending[1], "kind": pending[2], "confirmed": False}
        n, total = s.step_index + 1, len(proc.steps)
        # A "before" gate means the step text is not revealed until the user confirms.
        withheld = self._text_withheld(s)
        if withheld:
            assert pending
            say = f"{lead}Step {n} of {total}. Before I tell you this one: {pending[1]}"
        else:
            say = f"{lead}Step {n} of {total}. {step.text}"
            if pending:
                say += f" Before we go on: {pending[1]}"
        card = {
            "type": "step",
            "title": proc.title,
            "step_number": n,
            "step_total": total,
            "text": None if withheld else step.text,
            "text_withheld": withheld,
            "panel_labels": [] if withheld else step.panel_labels,
            "gate": gate,
            "blocked": blocked,
            "source": step.source.model_dump(),
            "procedure_id": proc.id,
            "step_id": None if withheld else step.id,
            "minutes": proc.minutes,
            "tools": proc.tools,
            "procedure_number": s.procedure_index + 1,
            "procedure_total": len(s.procedure_queue),
        }
        return self._out(s, say, card)

    def _paused(self, s: Session) -> Outcome:
        proc = self._procedure(s)
        assert proc
        n = (s.paused_step_index or 0) + 1
        say = f"We're paused at step {n} of {len(proc.steps)}. Say continue whenever you're ready."
        return self._out(
            s,
            say,
            {
                "type": "paused",
                "step_number": n,
                "step_total": len(proc.steps),
                "procedure": proc.title,
            },
        )

    def _verify(self, s: Session) -> Outcome:
        proc = self._procedure(s)
        assert proc
        say = f"That's every step. {proc.verify} Did it work?"
        return self._out(
            s,
            say,
            {
                "type": "verify",
                "procedure": proc.title,
                "verify": proc.verify,
                "source": proc.source.model_dump(),
            },
        )

    def _fixed(self, s: Session) -> Outcome:
        appliance = self._appliance(s)
        assert appliance
        card = {
            "type": "fixed",
            "error_code": s.error_code,
            "repeat_count": s.repeat_count,
            "health_card": self.services.health_card_data(appliance),
            "share_offer": not s.insight_shared,
        }
        say = "Wonderful, it's fixed. I've added it to your appliance's health card."
        if s.repeat_count > 1 and s.error_code:
            say += (
                f" That's the {ordinal(s.repeat_count)} time {s.error_code} has come up "
                "on this one, "
                "so keep an eye on it."
            )
        if not s.insight_shared:
            say += " Would you like to share what worked, anonymously, to help others?"
        return self._out(s, say, card)

    def _handoff(self, s: Session) -> Outcome:
        renter = self.store.household.renter
        say = (
            f"This one needs a technician. {s.handoff_reason} I can write up a summary for them"
            + (", or a message to your landlord." if renter else ".")
        )
        card = {
            "type": "handoff",
            "reason": s.handoff_reason,
            "error_code": s.error_code,
            "source": {"manual_id": s.manual_id, "page": s.handoff_page}
            if s.handoff_page
            else None,
            "renter": renter,
            "offers": ["technician_summary", *(["landlord_message"] if renter else [])],
        }
        return self._out(s, say, card)

    # --- transitions ---------------------------------------------------------------------

    def _enter_handoff(self, s: Session, reason: str, page: int | None) -> Outcome:
        s.state = State.HANDOFF
        s.handoff_reason = reason
        s.handoff_page = page
        appliance = self._appliance(s)
        if appliance:
            self.store.add_repair(
                appliance.id,
                PastRepair(
                    date=self.today(),
                    error_code=s.error_code,
                    fix="Handed off to a technician",
                    outcome="handed_off",
                    source=Source(manual_id=s.manual_id, page=page)
                    if s.manual_id and page
                    else None,
                ),
            )
        self._save(s, "handoff")
        return self._handoff(s)

    def _enter_stop(self, s: Session, details: str) -> Outcome:
        s.state = State.STOPPED
        s.safety_cleared = False
        s.safety_notes = details
        self._save(s, "stopped: danger reported")
        return self._stopped(s)

    def _close_fixed(self, s: Session, fix: str, page: int | None) -> Outcome:
        appliance = self._appliance(s)
        assert appliance
        s.state = State.FIXED
        source = Source(manual_id=s.manual_id, page=page) if s.manual_id and page else None
        self.store.add_repair(
            appliance.id,
            PastRepair(
                date=self.today(), error_code=s.error_code, fix=fix, outcome="fixed", source=source
            ),
        )
        self._save(s, "fixed")
        return self._fixed(s)

    def _appliance_named_in(self, description: str) -> str | None:
        """The appliance the user named, if they named exactly one."""
        said = description.lower()
        named = [
            a.id
            for a in self.store.appliances()
            if any(
                re.search(rf"\b{re.escape(word)}\b", said)
                for word in [a.type, *(k for k, v in TYPE_ALIASES.items() if v == a.type)]
            )
        ]
        return named[0] if len(named) == 1 else None

    def _danger_words(self, text: str) -> list[str]:
        keywords = set(self.store.safety["danger_keywords"])
        found = [w for w in re.findall(r"[a-z]+", text.lower()) if w in keywords]
        return list(dict.fromkeys(found))

    def _danger_in(self, text: str) -> bool:
        return bool(self._danger_words(text))

    def _note_mentions(self, s: Session, text: str) -> None:
        """Remember danger words that came with an explicit "no danger" answer."""
        for word in self._danger_words(text):
            if word not in s.danger_mentions:
                s.danger_mentions.append(word)

    def _prior_stop_for(self, description: str) -> dict[str, Any] | None:
        """The newest session was a safety stop: carry it over unless the user is clearly
        talking about a different appliance."""
        prior = self.store.latest_session()
        if not prior:
            return None
        if prior.state != State.STOPPED:
            # A repair that already inherited a stop passes it on, so asking to start again
            # cannot wash it away.
            open_ = prior.state not in (State.FIXED, State.HANDOFF)
            return prior.prior_stop if (prior.prior_stop and open_) else None
        appliances = self.store.appliances()
        said = description.lower()

        def mentioned(kind: str) -> bool:
            names = [kind] + [alias for alias, real in TYPE_ALIASES.items() if real == kind]
            return any(re.search(rf"\b{re.escape(n)}\b", said) for n in names)

        prior_appliance = next((a for a in appliances if a.id == prior.appliance_id), None)
        if prior_appliance and not mentioned(prior_appliance.type):
            if any(mentioned(a.type) for a in appliances if a.id != prior_appliance.id):
                return None
        words = self._danger_words(f"{prior.safety_notes} {prior.description}")
        return {
            "session_id": prior.id,
            "words": words,
            "appliance": prior_appliance.name if prior_appliance else None,
            "details": prior.safety_notes,
        }

    # --- tools: starting and safety -----------------------------------------------------------

    def start_repair(self, member_id: str | None = None, description: str = "") -> Outcome:
        if member_id and not self.store.household.member(member_id):
            return self._out(
                None,
                "I don't know who's speaking. Is it Priya or Lucia?",
                {"type": "unknown_member"},
                refused=True,
                reason="unknown_member",
            )
        latest = self.store.latest_session()
        if latest and latest.state == State.SAFETY_RECHECK:
            # An unanswered danger question cannot be dodged by starting over.
            return self._refuse(self._recheck_question(latest), "safety_recheck")
        prior_stop = self._prior_stop_for(description)
        s = self.store.new_session(member_id.lower() if member_id else None, description)
        s.appliance_hint = self._appliance_named_in(description)
        s.prior_stop = prior_stop
        self._save(
            s, f"carried safety stop from {prior_stop['session_id']}" if prior_stop else None
        )
        if self._danger_in(description):
            return self._enter_recheck(s, description)
        return self._safety_question(s)

    def get_repair_state(self, session_id: str | None = None) -> Outcome:
        s, err = self._resolve_any(session_id)
        return err if err else self.present(s)  # type: ignore[arg-type]

    def safety_check(
        self, session_id: str | None = None, danger_reported: bool = False, details: str = ""
    ) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        # The explicit answer is the only thing that stops or clears. Words in `details` are
        # not scanned: "no, I don't smell any burning" must not count as danger.
        if danger_reported:
            return self._enter_stop(s, details or s.recheck_text)
        self._note_mentions(s, details)
        if s.state == State.SAFETY_RECHECK:
            return self._leave_recheck(s, details)
        if s.state == State.SAFETY_CHECK:
            s.safety_cleared = True
            s.safety_notes = details
            s.state = State.IDENTIFY
            self._save(s, "safety cleared")
            return self._after_safety_clear(s)
        return self.present(s)

    def _after_safety_clear(self, s: Session) -> Outcome:
        """Ask which appliance, unless the user already named it: then confirm that one."""
        named = self.store.appliance(s.appliance_hint) if s.appliance_hint else None
        if named:
            out = self._identified(s, named)
            return out.model_copy(update={"say": "Good, thank you. " + out.say})
        out = self._ask_appliance(s)
        return out.model_copy(update={"say": "Good, thank you. " + out.say})

    def _leave_recheck(self, s: Session, details: str) -> Outcome:
        previous = s.recheck_from or State.SAFETY_CHECK
        self._note_mentions(s, s.recheck_text)
        s.recheck_from, s.recheck_text = None, ""
        if previous == State.SAFETY_CHECK:
            s.safety_cleared, s.safety_notes, s.state = True, details, State.IDENTIFY
            self._save(s, "safety cleared after recheck")
            return self._after_safety_clear(s)
        s.state = previous
        self._save(s, "safety recheck cleared")
        out = self.present(s)
        return out.model_copy(update={"say": "Okay, thank you. Let's carry on. " + out.say})

    # --- tools: identify, manual, quick checks, diagnose --------------------------------------

    def identify_appliance(
        self,
        session_id: str | None = None,
        appliance_id: str | None = None,
        model_code: str | None = None,
        appliance_type: str | None = None,
    ) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.IDENTIFY, State.MANUAL}):
            return refusal
        if s.appliance_id and not (appliance_id or model_code or appliance_type):
            return self.present(s)  # already identified: asking again must not undo that
        found = self._match_appliances(appliance_id, model_code, appliance_type)
        if not found and s.appliance_id:
            return self.present(s)  # an id that matches nothing must not undo what is known
        if len(found) != 1:
            ask = self._ask_appliance(s)
            if model_code and not found:
                ask = ask.model_copy(
                    update={
                        "say": "I couldn't match that model code. I can also look through your "
                        "order history, if you'd like. " + ask.say
                    }
                )
            return ask
        return self._identified(s, found[0])

    def _identified(self, s: Session, a: Appliance) -> Outcome:
        s.appliance_id, s.manual_id, s.state = a.id, a.manual_id, State.MANUAL
        self._save(s, f"identified {a.id}")
        say = (
            f"That sounds like your {a.name} in the {a.room}, model code {a.model_code}. "
            "Is that the one?"
        )
        return self._out(
            s,
            say,
            {
                "type": "appliance",
                "appliance_id": a.id,
                "name": a.name,
                "model_code": a.model_code,
                "room": a.room,
            },
        )

    def _match_appliances(
        self, appliance_id: str | None, model_code: str | None, appliance_type: str | None
    ) -> list[Appliance]:
        """Try each identifier in turn and use the first that finds something. A model may pass
        a wrong id next to a right model code, and the right one should still win."""
        appliances = self.store.appliances()
        if appliance_id:
            wanted = appliance_id.lower().strip()
            found = [a for a in appliances if wanted in (a.id, a.manual_id)]
            code = normalize_code(wanted)  # "dw-300" and "DW300" are the model name
            found = found or [
                a
                for a in appliances
                if code and code in (normalize_code(a.model), normalize_code(a.model_code))
            ]
            if found:
                return found
        if model_code:
            wanted = normalize_code(model_code)
            found = [
                a
                for a in appliances
                if wanted
                and (
                    wanted.startswith(normalize_code(a.model))
                    or normalize_code(a.model_code).startswith(wanted)
                )
            ]
            if found:
                return found
        if appliance_type:
            kind = TYPE_ALIASES.get(appliance_type.lower().strip(), appliance_type.lower().strip())
            return [a for a in appliances if a.type == kind]
        return []

    def find_manual(self, session_id: str | None = None, manual_id: str | None = None) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if s.state == State.MANUAL:
            assert s.manual_id
            if manual_id and manual_id != s.manual_id:
                return self._out(
                    s,
                    "That isn't the manual for your appliance.",
                    {"type": "wrong_manual"},
                    refused=True,
                    reason="wrong_manual",
                )
            s.state = State.QUICK_CHECKS
            self._save(s, "manual confirmed")
        elif refusal := self._guard(
            s,
            {
                State.QUICK_CHECKS,
                State.DIAGNOSE,
                State.PREPARE,
                State.STEPS,
                State.PAUSED,
                State.VERIFY,
            },
        ):
            return refusal
        manual = self._manual(s)
        assert manual
        title = manual.title.removesuffix(" (fictional)")
        if s.state == State.QUICK_CHECKS:
            # The quick checks come with the manual, so nothing has to be improvised between the
            # two calls, and the checks always come from the manual.
            checks = self._quick_checks_card(s)
            card = {**checks.card, "manual": self.services.manual_card(manual)}
            return checks.model_copy(
                update={"say": f"Found the {title}. {checks.say}", "card": card}
            )
        sticker = manual.model_sticker
        say = (
            f"The {title}. The model sticker is on page {sticker.page}: {sticker.location.lower()}"
        )
        return self._out(s, say, self.services.manual_card(manual))

    def quick_checks(
        self, session_id: str | None = None, setting_fixed: bool | None = None, note: str = ""
    ) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.QUICK_CHECKS, State.DIAGNOSE}):
            return refusal
        if self._danger_in(note):
            return self._enter_recheck(s, note)
        if setting_fixed is True:
            page = self._manual(s).quick_checks[0].source.page  # type: ignore[union-attr]
            return self._close_fixed(s, f"Quick check: {note or 'a setting was the cause'}", page)
        if setting_fixed is False:
            s.state = State.DIAGNOSE
            self._save(s, "quick checks did not fix it")
            return self._out(
                s, "Okay, those weren't it. " + self._ask_code(s).say, self._ask_code(s).card
            )
        return self._quick_checks_card(s)

    def diagnose(
        self, session_id: str | None = None, error_code: str | None = None, symptoms: str = ""
    ) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.QUICK_CHECKS, State.DIAGNOSE}):
            return refusal
        if self._danger_in(symptoms):
            return self._enter_recheck(s, symptoms)
        if s.state == State.QUICK_CHECKS and not s.quick_checks_shown:
            return self._refuse(
                self._quick_checks_card(s), "quick_checks_first", "Simple things first. "
            )
        manual = self._manual(s)
        appliance = self._appliance(s)
        assert manual and appliance
        s.symptoms = symptoms or s.symptoms
        if reason := self._technician_topic(symptoms):
            s.error_code = error_code or s.error_code
            return self._enter_handoff(s, reason, None)
        if not error_code:
            s.state = State.DIAGNOSE
            self._save(s)
            return self._ask_code(s)
        code = manual.error_code(error_code)
        if not code:
            s.state = State.DIAGNOSE
            self._save(s, f"unknown code {error_code}")
            return self._ask_code(s, entered=error_code)
        s.error_code = code.code
        if code.diy == "technician_only":
            assert code.technician_reason
            return self._enter_handoff(s, code.technician_reason, code.page)
        s.procedure_queue = list(code.procedure_ids)
        s.procedure_index, s.step_index = 0, -1
        s.confirmed_gates, s.reconfirm_gate = [], None
        s.repeat_count = prior_occurrences(appliance, code.code) + 1
        s.state = State.PREPARE
        self._save(s, f"diagnosed {code.code}")
        out = self._prepare(s)
        if s.repeat_count > 1:
            last = next(
                r
                for r in reversed(appliance.past_repairs)
                if r.error_code and normalize_code(r.error_code) == normalize_code(code.code)
            )
            out.card["last_repair"] = last.model_dump(mode="json")
        return out

    def _technician_topic(self, text: str) -> str | None:
        lowered = text.lower()
        for topic in self.store.safety["technician_only_topics"]:
            if any(k in lowered for k in topic["keywords"]):
                return topic["reason"]
        return None

    # --- tools: steps -------------------------------------------------------------------------

    def next_step(self, session_id: str | None = None, repeat: bool = False) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.PREPARE, State.STEPS}):
            return refusal
        proc = self._procedure(s)
        assert proc
        if repeat:
            return self.present(s)
        if s.state == State.PREPARE:
            s.state, s.step_index = State.STEPS, 0
            self._save(s, f"started {proc.id}")
            return self._step(s)
        if pending := self._pending_gate(s):
            return self._refuse(
                self._step(s, blocked=True),
                "gate_unconfirmed",
                f"Not yet, safety first. {pending[1]} Tell me once that's done. ",
            )
        if s.step_index >= len(proc.steps) - 1:
            s.state = State.VERIFY
            self._save(s, f"finished steps of {proc.id}")
            return self._verify(s)
        s.step_index += 1
        self._save(s)
        return self._step(s)

    def confirm_gate(self, session_id: str | None = None, confirmed: bool = True) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.STEPS}):
            return refusal
        pending = self._pending_gate(s)
        if not pending:
            return self._step(s, lead="Nothing needs confirming right now. ")
        if not confirmed:
            return self._out(
                s,
                f"No problem. Take your time, and tell me when: {pending[1]}",
                self._step(s, blocked=True).card,
                refused=True,
                reason="gate_declined",
            )
        key = pending[0]
        s.confirmed_gates.append(key)
        if s.reconfirm_gate == key:
            s.reconfirm_gate = None
        self._save(s, f"confirmed gate {key}")
        return self._step(s, lead="Thank you. ")

    def pause_repair(self, session_id: str | None = None) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.STEPS}):
            return refusal
        s.state, s.paused_step_index = State.PAUSED, s.step_index
        self._save(s, "paused")
        return self._paused(s)

    def resume_repair(self, session_id: str | None = None) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.PAUSED}):
            return refusal
        proc = self._procedure(s)
        assert proc and s.paused_step_index is not None
        s.state, s.step_index = State.STEPS, s.paused_step_index
        s.paused_step_index = None
        # Someone may have plugged things back in while we were away: ask the latest gate again.
        for i in range(s.step_index, -1, -1):
            step = proc.steps[i]
            key = _gate_key(proc, step.id)
            if step.gate and key in s.confirmed_gates:
                s.confirmed_gates.remove(key)
                s.reconfirm_gate = key
                break
        self._save(s, "resumed")
        return self._step(s, lead=f"We stopped at step {s.step_index + 1}. ")

    def go_back(self, session_id: str | None = None) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.STEPS, State.VERIFY}):
            return refusal
        proc = self._procedure(s)
        assert proc
        if s.state == State.VERIFY:
            s.state, s.step_index = State.STEPS, len(proc.steps) - 1
        elif s.step_index == 0:
            return self._refuse(self._step(s), "at_first_step", "That's the first step. ")
        else:
            s.step_index -= 1
        self._save(s, "went back")
        return self._step(s, lead="Going back. ")

    def report_result(
        self, session_id: str | None = None, fixed: bool = False, notes: str = ""
    ) -> Outcome:
        s, err = self._resolve(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard(s, {State.STEPS, State.VERIFY, State.PAUSED}):
            return refusal
        manual, proc = self._manual(s), self._procedure(s)
        assert manual and proc
        if self._danger_in(notes):
            return self._enter_recheck(s, notes)
        last = len(proc.steps) - 1
        if fixed and s.state == State.STEPS and s.step_index == last:
            if self._pending_gate(s):  # same rule as next_step: a gate holds until confirmed
                return self._refuse(self._step(s, blocked=True), "gate_unconfirmed")
            # "Fixed" is only recorded once the user has been asked whether it worked.
            s.state = State.VERIFY
            self._save(s, "finished steps, verifying")
            return self._refuse(self._verify(s), "verify_first")
        if fixed and s.state != State.VERIFY:
            return self._refuse(
                self.present(s), "steps_unfinished", "Let's finish the steps first. "
            )
        done = (
            len(proc.steps)
            if s.state == State.VERIFY
            else (s.paused_step_index if s.state == State.PAUSED else s.step_index) + 1
        )
        s.attempts.append(
            Attempt(
                procedure_id=proc.id,
                title=proc.title,
                page=proc.source.page,
                steps_completed=done,
                result="fixed" if fixed else "not_fixed",
            )
        )
        if notes:
            s.log.append(f"result note: {notes}")
        if fixed:
            return self._close_fixed(s, proc.title, proc.source.page)
        s.procedure_index += 1
        if s.procedure_id:
            s.state, s.step_index, s.paused_step_index = State.PREPARE, -1, None
            s.reconfirm_gate = None
            self._save(s, f"{proc.id} not fixed, trying next")
            return self._prepare(s)
        code = manual.error_code(s.error_code or "")
        if code and code.escalate_if_unfixed and code.technician_reason and code.escalation_source:
            return self._enter_handoff(s, code.technician_reason, code.escalation_source.page)
        page = code.page if code else proc.source.page
        return self._enter_handoff(
            s,
            f"We've tried everything the manual suggests for {s.error_code or 'this problem'}.",
            page,
        )

    # --- tools: handoff documents -------------------------------------------------------------

    def _safety_notes(self, s: Session) -> str:
        notes = [s.safety_notes] if s.safety_notes else []
        if s.danger_mentions:
            notes.append(
                "The user used these words about danger, then answered that nothing "
                f"dangerous was happening: {_words(s.danger_mentions)}."
            )
        if s.prior_stop:
            earlier = _words(s.prior_stop["words"]) or "a safety problem"
            notes.append(f"An earlier repair was stopped for safety ({earlier}).")
        return " ".join(notes)

    def create_technician_summary(self, session_id: str | None = None) -> Outcome:
        s, err = self._resolve_any(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard_handoff(s):
            return refusal
        appliance, manual = self._appliance(s), self._manual(s)
        code = manual.error_code(s.error_code) if manual and s.error_code else None
        tried = [a.model_dump() for a in s.attempts]
        card = {
            "type": "technician_summary",
            "language": "en",
            "appliance": appliance.name if appliance else None,
            "model_code": appliance.model_code if appliance else None,
            "purchase_date": appliance.purchase_date.isoformat() if appliance else None,
            "error_code": s.error_code,
            "meaning": code.meaning if code else None,
            "reported": s.description or s.symptoms,
            "tried": tried,
            "reason": s.handoff_reason,
            "safety_notes": self._safety_notes(s),
            "danger_mentions": s.danger_mentions,
            "source": {"manual_id": s.manual_id, "page": s.handoff_page}
            if s.handoff_page
            else None,
        }
        what = (
            "no steps yet"
            if not tried
            else _words([f"{t['title'].lower()} (page {t['page']})" for t in tried])
        )
        say = (
            f"Here's the summary for the technician: {card['appliance'] or 'the appliance'}"
            + (f", error {s.error_code}" if s.error_code else "")
            + f". We tried: {what}."
        )
        return self._out(s, say, card)

    def draft_landlord_message(self, session_id: str | None = None) -> Outcome:
        s, err = self._resolve_any(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if refusal := self._guard_handoff(s):
            return refusal
        hh = self.store.household
        if not hh.renter or not hh.landlord:
            return self._refuse(
                self._out(
                    s,
                    "You own your home, so there's no landlord to write to.",
                    {"type": "not_renter"},
                ),
                "not_renter",
            )
        appliance, manual = self._appliance(s), self._manual(s)
        code = manual.error_code(s.error_code) if manual and s.error_code else None
        member = hh.member(s.member_id)
        lines = [f"Hello {hh.landlord.name},", ""]
        subject_item = appliance.name if appliance else "an appliance"
        problem = f"is showing error {s.error_code}" if s.error_code else "has a problem"
        if code:
            problem += f" ({code.meaning.lower()})"
        where = f" in the {appliance.room}" if appliance else ""
        lines.append(
            f"The {subject_item}{where} {problem}"
            + (f" (model code {appliance.model_code})." if appliance else ".")
        )
        if s.attempts:
            tried = "; ".join(
                f"{a.title.lower()} (manual page {a.page}), "
                f"{'fixed it' if a.result == 'fixed' else 'did not fix it'}"
                for a in s.attempts
            )
            lines.append(f"We followed the manufacturer's manual and tried: {tried}.")
        if s.handoff_reason:
            lines.append(s.handoff_reason)
        lines += [
            "Could you please arrange a technician visit?",
            "",
            "Thank you,",
            member.name if member else "Your tenant",
        ]
        subject = f"Repair request: {subject_item}" + (
            f", error {s.error_code}" if s.error_code else ""
        )
        card = {
            "type": "landlord_message",
            "language": "en",
            "to": hh.landlord.name,
            "contact": hh.landlord.contact,
            "subject": subject,
            "body": "\n".join(lines),
        }
        say = (
            f"I've drafted a message to {hh.landlord.name}. It says the {subject_item} {problem}, "
            "what we tried, and asks for a technician visit."
        )
        return self._out(s, say, card)

    def _guard_handoff(self, s: Session) -> Outcome | None:
        if s.state in (State.HANDOFF, State.STOPPED):
            return None
        if s.state == State.SAFETY_RECHECK:
            return self._refuse(self._recheck_question(s), "safety_recheck")
        if s.state == State.SAFETY_CHECK:
            return self._refuse(self._safety_question(s), "safety_first")
        return self._refuse(self.present(s), "not_in_handoff", "We haven't handed this off yet. ")

    # --- tools: anonymous insight -------------------------------------------------------------

    def share_insight(self, session_id: str | None = None, consent: bool = False) -> Outcome:
        s, err = self._resolve_any(session_id)
        if err or not s:
            return err  # type: ignore[return-value]
        if s.state != State.FIXED:
            return self._refuse(self.present(s), "not_fixed_yet", "There's nothing to share yet. ")
        appliance = self._appliance(s)
        assert appliance
        if not consent:
            return self._out(
                s,
                "I'd share only the appliance model, the error code and what fixed it. No names, "
                "no address. Is that okay?",
                {
                    "type": "consent",
                    "topic": "insight_sharing",
                    "shares": ["model", "error_code", "fix"],
                    "never_shares": ["name", "address", "household"],
                },
                refused=True,
                reason="consent_required",
            )
        if not s.insight_shared:
            fix = s.attempts[-1].title if s.attempts else "Quick check"
            self.store.add_contribution(
                {"model": appliance.model, "error_code": s.error_code or "", "fix": fix}
            )
            s.insight_shared = True
            self._save(s, "insight shared")
        return self._out(
            s,
            "Thank you. I shared it anonymously.",
            {"type": "insight_shared", "model": appliance.model, "error_code": s.error_code},
        )

    def _resolve_any(self, session_id: str | None) -> tuple[Session | None, Outcome | None]:
        return self._resolve(session_id)
