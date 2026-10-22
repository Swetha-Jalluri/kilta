"""Typed models for Kilta data files, repair sessions, and tool outcomes."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Source(BaseModel):
    """Where a fact or step comes from. Every repair step must carry one."""

    manual_id: str = Field(min_length=1)
    page: int = Field(ge=1)


class Gate(BaseModel):
    prompt: str = Field(min_length=1)


class Step(BaseModel):
    id: str
    text: str = Field(min_length=1)
    source: Source
    panel_labels: list[str] = Field(default_factory=list)
    gate: Gate | None = None


class QuickCheck(BaseModel):
    id: str
    text: str
    panel_labels: list[str] = Field(default_factory=list)
    source: Source


class Procedure(BaseModel):
    id: str
    title: str
    source: Source
    minutes: int = Field(ge=1)
    tools: list[str] = Field(default_factory=list)
    fixes: list[str] = Field(default_factory=list)
    verify: str
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_step_ids(self) -> Procedure:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"procedure {self.id}: duplicate step ids")
        return self


class ErrorCode(BaseModel):
    code: str
    meaning: str
    page: int = Field(ge=1)
    causes: list[str] = Field(default_factory=list)
    diy: Literal["yes", "technician_only"]
    procedure_ids: list[str] = Field(default_factory=list)
    technician_reason: str | None = None
    escalate_if_unfixed: bool = False
    escalation_source: Source | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ErrorCode:
        if self.diy == "technician_only":
            if self.procedure_ids:
                raise ValueError(f"{self.code}: technician-only codes cannot have DIY procedures")
            if not self.technician_reason:
                raise ValueError(f"{self.code}: technician-only codes need technician_reason")
        elif not self.procedure_ids:
            raise ValueError(f"{self.code}: DIY codes need at least one procedure")
        if self.escalate_if_unfixed and not (self.technician_reason and self.escalation_source):
            raise ValueError(
                f"{self.code}: escalation needs technician_reason and escalation_source"
            )
        return self


class Part(BaseModel):
    sku: str
    name: str
    price_usd: float = Field(ge=0)
    fits: list[str] = Field(default_factory=list)


class ModelSticker(BaseModel):
    location: str
    page: int = Field(ge=1)


class Manual(BaseModel):
    id: str
    title: str
    brand: str
    model: str
    appliance_type: str
    model_sticker: ModelSticker
    model_code_format: str
    quick_checks: list[QuickCheck]
    error_codes: list[ErrorCode]
    procedures: list[Procedure]
    parts: list[Part] = Field(default_factory=list)

    @model_validator(mode="after")
    def _grounded(self) -> Manual:
        procedures = {p.id for p in self.procedures}
        sources = [qc.source for qc in self.quick_checks]
        for proc in self.procedures:
            sources.append(proc.source)
            sources.extend(step.source for step in proc.steps)
        for code in self.error_codes:
            if missing := set(code.procedure_ids) - procedures:
                raise ValueError(f"{code.code}: unknown procedures {sorted(missing)}")
            if code.escalation_source:
                sources.append(code.escalation_source)
        for src in sources:
            if src.manual_id != self.id:
                raise ValueError(f"source cites {src.manual_id!r} inside manual {self.id!r}")
        return self

    def error_code(self, raw: str) -> ErrorCode | None:
        wanted = normalize_code(raw)
        return next((c for c in self.error_codes if normalize_code(c.code) == wanted), None)

    def procedure(self, procedure_id: str) -> Procedure:
        return next(p for p in self.procedures if p.id == procedure_id)


def normalize_code(raw: str) -> str:
    return "".join(ch for ch in raw.upper() if ch.isalnum())


class PastRepair(BaseModel):
    date: date
    error_code: str | None = None
    fix: str
    outcome: Literal["fixed", "not_fixed", "handed_off"]
    source: Source | None = None


class Appliance(BaseModel):
    id: str
    manual_id: str
    type: str
    name: str
    brand: str
    model: str
    model_code: str
    room: str
    purchase_date: date
    past_repairs: list[PastRepair] = Field(default_factory=list)


class Member(BaseModel):
    id: str
    name: str
    language: str
    confidence: Literal["beginner", "some", "confident"]
    pace: Literal["slow", "normal", "fast"]


class Landlord(BaseModel):
    name: str
    contact: str


class Household(BaseModel):
    id: str
    name: str
    renter: bool
    landlord: Landlord | None = None
    members: list[Member]
    preferences: dict[str, str] = Field(default_factory=dict)

    def member(self, member_id: str | None) -> Member | None:
        if member_id is None:
            return None
        return next((m for m in self.members if m.id == member_id.lower()), None)


class State(StrEnum):
    SAFETY_CHECK = "SAFETY_CHECK"
    STOPPED = "STOPPED"
    IDENTIFY = "IDENTIFY"
    MANUAL = "MANUAL"
    QUICK_CHECKS = "QUICK_CHECKS"
    DIAGNOSE = "DIAGNOSE"
    PREPARE = "PREPARE"
    STEPS = "STEPS"
    PAUSED = "PAUSED"
    VERIFY = "VERIFY"
    FIXED = "FIXED"
    HANDOFF = "HANDOFF"


TERMINAL_STATES = frozenset({State.STOPPED, State.FIXED, State.HANDOFF})


class Attempt(BaseModel):
    procedure_id: str
    title: str
    page: int
    steps_completed: int
    result: Literal["fixed", "not_fixed"]


class Session(BaseModel):
    id: str
    member_id: str | None = None
    state: State = State.SAFETY_CHECK
    description: str = ""
    created_at: str
    updated_at: str

    safety_cleared: bool = False
    safety_notes: str = ""

    appliance_id: str | None = None
    manual_id: str | None = None
    quick_checks_shown: bool = False
    error_code: str | None = None
    symptoms: str = ""

    procedure_queue: list[str] = Field(default_factory=list)
    procedure_index: int = 0
    step_index: int = -1
    confirmed_gates: list[str] = Field(default_factory=list)
    reconfirm_gate: str | None = None
    paused_step_index: int | None = None

    attempts: list[Attempt] = Field(default_factory=list)
    handoff_reason: str | None = None
    handoff_page: int | None = None
    repeat_count: int = 0
    insight_shared: bool = False
    log: list[str] = Field(default_factory=list)

    @property
    def procedure_id(self) -> str | None:
        if self.procedure_index < len(self.procedure_queue):
            return self.procedure_queue[self.procedure_index]
        return None


class Outcome(BaseModel):
    """What every engine call returns; tools turn it into content + structuredContent."""

    say: str
    card: dict[str, Any]
    session: Session | None = None
    refused: bool = False
    reason: str | None = None

    def structured(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "card": self.card,
            "state": self.session.state.value if self.session else None,
            "session_id": self.session.id if self.session else None,
            "refused": self.refused,
        }
        if self.reason:
            out["reason"] = self.reason
        return out
