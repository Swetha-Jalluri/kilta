"""Household, catalog, and simulated-service lookups. No repair-flow state lives here."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from .data import DataStore
from .models import Appliance, Manual, Outcome, Session, normalize_code

WARRANTY_MONTHS = 24

ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}


def ordinal(n: int) -> str:
    return ORDINALS.get(n, f"{n}th")


def _add_months(start: date, months: int) -> date:
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    last_day = [
        31,
        29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ][month - 1]
    return date(year, month, min(start.day, last_day))


def warranty_status(appliance: Appliance, today: date) -> dict[str, Any]:
    ends = _add_months(appliance.purchase_date, WARRANTY_MONTHS)
    return {
        "appliance_id": appliance.id,
        "purchased": appliance.purchase_date.isoformat(),
        "coverage_months": WARRANTY_MONTHS,
        "ends": ends.isoformat(),
        "in_warranty": today <= ends,
        "estimate": True,
    }


def repeat_counts(appliance: Appliance) -> dict[str, int]:
    counts: dict[str, int] = {}
    for repair in appliance.past_repairs:
        if repair.error_code:
            key = normalize_code(repair.error_code)
            counts[key] = counts.get(key, 0) + 1
    return counts


def prior_occurrences(appliance: Appliance, error_code: str) -> int:
    return repeat_counts(appliance).get(normalize_code(error_code), 0)


class Services:
    def __init__(self, store: DataStore, today: Callable[[], date] = date.today) -> None:
        self.store = store
        self.today = today

    def _out(
        self,
        say: str,
        card: dict[str, Any],
        *,
        session: Session | None = None,
        refused: bool = False,
        reason: str | None = None,
    ) -> Outcome:
        return Outcome(say=say, card=card, session=session, refused=refused, reason=reason)

    def _appliance_or_refuse(
        self, appliance_id: str | None
    ) -> tuple[Appliance | None, Outcome | None]:
        appliance = self.store.appliance(appliance_id) if appliance_id else None
        if appliance:
            return appliance, None
        names = ", ".join(f"{a.id} ({a.name})" for a in self.store.appliances())
        return None, self._out(
            f"I don't know that appliance. I can see: {names}.",
            {"type": "appliance_list", "appliances": [a.id for a in self.store.appliances()]},
            refused=True,
            reason="unknown_appliance",
        )

    # --- household and appliances ------------------------------------------------------

    def get_household(self, member_id: str | None = None) -> Outcome:
        hh = self.store.household
        member = hh.member(member_id)
        speaker = member or hh.members[0]
        greeting = f"Hi {speaker.name}, it's Kilta."
        if member is None and member_id:
            greeting = "Hi, it's Kilta."
        names = " and ".join(a.name for a in self.store.appliances())
        card = {
            "type": "household",
            "household": hh.model_dump(mode="json"),
            "speaker": member.model_dump(mode="json") if member else None,
            "appliances": [a.id for a in self.store.appliances()],
        }
        return self._out(f"{greeting} I know about your {names}. What's going on?", card)

    def list_appliances(self) -> Outcome:
        items = [
            {
                "id": a.id,
                "name": a.name,
                "room": a.room,
                "model_code": a.model_code,
                "purchase_date": a.purchase_date.isoformat(),
                "repairs": len(a.past_repairs),
            }
            for a in self.store.appliances()
        ]
        speech = (
            "You have " + " and ".join(f"a {i['name']} in the {i['room']}" for i in items) + "."
        )
        return self._out(speech, {"type": "appliance_list", "appliances": items})

    def health_card_data(self, appliance: Appliance) -> dict[str, Any]:
        repeats = {code: n for code, n in repeat_counts(appliance).items() if n > 1}
        return {
            "type": "health_card",
            "appliance": {
                "id": appliance.id,
                "name": appliance.name,
                "model_code": appliance.model_code,
                "room": appliance.room,
                "purchase_date": appliance.purchase_date.isoformat(),
            },
            "repairs": [r.model_dump(mode="json") for r in appliance.past_repairs],
            "repeat_codes": repeats,
            "warranty": warranty_status(appliance, self.today()),
        }

    def get_health_card(self, appliance_id: str) -> Outcome:
        appliance, err = self._appliance_or_refuse(appliance_id)
        if err or not appliance:
            return err  # type: ignore[return-value]
        n = len(appliance.past_repairs)
        history = (
            "no repairs on record" if n == 0 else f"{n} repair{'s' if n != 1 else ''} on record"
        )
        last = appliance.past_repairs[-1] if n else None
        tail = f" The latest was {last.fix.lower()} on {last.date.isoformat()}." if last else ""
        return self._out(
            f"Your {appliance.name} has {history}.{tail}", self.health_card_data(appliance)
        )

    def check_warranty(self, appliance_id: str) -> Outcome:
        appliance, err = self._appliance_or_refuse(appliance_id)
        if err or not appliance:
            return err  # type: ignore[return-value]
        w = warranty_status(appliance, self.today())
        verdict = "is probably still covered" if w["in_warranty"] else "is probably out of warranty"
        say = (
            f"Your {appliance.name} {verdict}. This is an estimate: {WARRANTY_MONTHS} months "
            f"from {w['purchased']}, ending {w['ends']}. Check your paperwork to be sure."
        )
        return self._out(say, {"type": "warranty", **w, "appliance": appliance.name})

    # --- simulated order history -------------------------------------------------------

    def lookup_orders(self, consent: bool) -> Outcome:
        if not consent:
            return self._out(
                "I can look through your order history for appliances only, nothing else. "
                "Is that okay?",
                {"type": "consent", "topic": "order_history", "scope": "appliances only"},
                refused=True,
                reason="consent_required",
            )
        orders = [o for o in self.store.orders["orders"] if o["category"] == "appliance"]
        say = "I found " + " and ".join(f"a {o['item']} from {o['date']}" for o in orders) + "."
        return self._out(
            say,
            {
                "type": "orders",
                "simulated": True,
                "orders": orders,
                "note": self.store.orders["note"],
            },
        )

    # --- manuals -----------------------------------------------------------------------

    def manual_card(self, manual: Manual) -> dict[str, Any]:
        pages = [c.page for c in manual.error_codes]
        sections = [
            {"title": "Quick checks", "page": manual.quick_checks[0].source.page},
            {"title": "Error codes", "page": min(pages), "page_end": max(pages)},
            *({"title": p.title, "page": p.source.page} for p in manual.procedures),
        ]
        return {
            "type": "manual",
            "manual_id": manual.id,
            "title": manual.title,
            "model": manual.model,
            "model_sticker": manual.model_sticker.model_dump(),
            "sections": sections,
        }

    def search_manual(
        self, query: str, manual_id: str | None = None, appliance_id: str | None = None
    ) -> Outcome:
        """Section titles and page numbers only. Step-by-step text comes from the engine."""
        if appliance_id and (a := self.store.appliance(appliance_id)):
            manual_id = a.manual_id
        manuals = (
            [self.store.manuals[manual_id]]
            if manual_id in self.store.manuals
            else (list(self.store.manuals.values()))
        )
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1]
        hits: list[dict[str, Any]] = []
        for m in manuals:
            for code in m.error_codes:
                hay = f"{code.code} {code.meaning} {' '.join(code.causes)}".lower()
                if any(w in hay for w in words):
                    hits.append(
                        {
                            "manual_id": m.id,
                            "kind": "error_code",
                            "title": f"{code.code}: {code.meaning}",
                            "page": code.page,
                            "technician_only": code.diy == "technician_only",
                        }
                    )
            for proc in m.procedures:
                hay = f"{proc.title} {' '.join(proc.fixes)} {' '.join(proc.tools)}".lower()
                if any(w in hay for w in words):
                    hits.append(
                        {
                            "manual_id": m.id,
                            "kind": "procedure",
                            "title": proc.title,
                            "page": proc.source.page,
                            "technician_only": False,
                        }
                    )
        hits = hits[:5]
        if not hits:
            return self._out(
                "I couldn't find that in the manual.",
                {"type": "manual_search", "query": query, "results": []},
            )
        top = hits[0]
        say = f"The best match is {top['title']}, on page {top['page']} of the manual."
        return self._out(say, {"type": "manual_search", "query": query, "results": hits})

    # --- simulated cart ----------------------------------------------------------------

    def build_parts_cart(self, appliance_id: str, skus: list[str], confirm: bool) -> Outcome:
        appliance, err = self._appliance_or_refuse(appliance_id)
        if err or not appliance:
            return err  # type: ignore[return-value]
        manual = self.store.manual_for(appliance)
        by_sku = {p.sku: p for p in manual.parts}
        if not skus:
            card = {
                "type": "cart",
                "status": "suggestions",
                "simulated": True,
                "parts": [p.model_dump() for p in manual.parts],
            }
            return self._out("Here are the parts that fit. Tell me which ones you'd like.", card)
        unknown = [s for s in skus if s not in by_sku]
        if unknown:
            return self._out(
                f"That part doesn't fit your {appliance.model}.",
                {"type": "cart", "status": "invalid", "simulated": True, "unknown": unknown},
                refused=True,
                reason="unknown_part",
            )
        parts = [by_sku[s] for s in skus]
        total = round(sum(p.price_usd for p in parts), 2)
        card = {
            "type": "cart",
            "simulated": True,
            "parts": [p.model_dump() for p in parts],
            "total_usd": total,
            "status": "created" if confirm else "needs_confirmation",
        }
        if not confirm:
            say = (
                f"That's {len(parts)} item{'s' if len(parts) != 1 else ''}, ${total:.2f}. "
                "Nothing is bought yet. Should I put it in the cart?"
            )
            return self._out(say, card, refused=True, reason="confirmation_required")
        return self._out(
            f"Done. It's in your cart for ${total:.2f}. This is a demo, so nothing was bought.",
            card,
        )

    # --- anonymous insights ------------------------------------------------------------

    def get_insights(self, model: str | None = None) -> Outcome:
        entries = [dict(e) for e in self.store.insights_base["entries"]]
        for contribution in self.store.contributions():
            for e in entries:
                if e["model"] == contribution["model"] and normalize_code(
                    e["error_code"]
                ) == normalize_code(contribution["error_code"]):
                    e["reports"] += 1
        if model:
            entries = [e for e in entries if e["model"].lower() == model.lower()]
        if not entries:
            return self._out(
                "I don't have any shared insights for that yet.",
                {"type": "insights", "synthetic": True, "entries": []},
            )
        top = max(entries, key=lambda e: e["reports"])
        say = (
            f"Across shared reports, {top['model']} error {top['error_code']} is the most common, "
            f"fixed at home {top['fixed_at_home_pct']} percent of the time. "
            "This is synthetic demo data."
        )
        return self._out(
            say,
            {
                "type": "insights",
                "synthetic": True,
                "note": self.store.insights_base["note"],
                "entries": entries,
            },
        )
