"""Loads the fictional data files and persists runtime state (sessions, repair history)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    TERMINAL_STATES,
    Appliance,
    Household,
    Manual,
    PastRepair,
    Session,
)


def default_data_dir() -> Path:
    if env := os.environ.get("KILTA_DATA_DIR"):
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class DataStore:
    """Static data is validated at load time. Runtime state lives under data/state and
    data/sessions, so `make reset` is just deleting those two folders."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.household = Household.model_validate(_read(self.dir / "household.json"))
        self._appliances = [
            Appliance.model_validate(a) for a in _read(self.dir / "appliances.json")["appliances"]
        ]
        self.manuals: dict[str, Manual] = {}
        for path in sorted((self.dir / "manuals").glob("*.json")):
            manual = Manual.model_validate(_read(path))
            self.manuals[manual.id] = manual
        for appliance in self._appliances:
            if appliance.manual_id not in self.manuals:
                raise ValueError(f"{appliance.id}: unknown manual {appliance.manual_id}")
        self.orders: dict[str, Any] = _read(self.dir / "orders.json")
        self.insights_base: dict[str, Any] = _read(self.dir / "insights.json")
        self.safety: dict[str, Any] = _read(self.dir / "safety.json")

    # --- appliances and repair history -------------------------------------------------

    @property
    def _repairs_path(self) -> Path:
        return self.dir / "state" / "repairs.json"

    def _repair_overlay(self) -> dict[str, list[dict[str, Any]]]:
        return _read(self._repairs_path) if self._repairs_path.exists() else {}

    def appliances(self) -> list[Appliance]:
        overlay = self._repair_overlay()
        merged = []
        for appliance in self._appliances:
            extra = [PastRepair.model_validate(r) for r in overlay.get(appliance.id, [])]
            merged.append(
                appliance.model_copy(update={"past_repairs": [*appliance.past_repairs, *extra]})
            )
        return merged

    def appliance(self, appliance_id: str) -> Appliance | None:
        return next((a for a in self.appliances() if a.id == appliance_id), None)

    def manual_for(self, appliance: Appliance) -> Manual:
        return self.manuals[appliance.manual_id]

    def add_repair(self, appliance_id: str, repair: PastRepair) -> None:
        overlay = self._repair_overlay()
        overlay.setdefault(appliance_id, []).append(repair.model_dump(mode="json"))
        _write(self._repairs_path, overlay)

    # --- anonymous insights ------------------------------------------------------------

    @property
    def _contrib_path(self) -> Path:
        return self.dir / "state" / "insight_contributions.json"

    def contributions(self) -> list[dict[str, Any]]:
        return _read(self._contrib_path) if self._contrib_path.exists() else []

    def add_contribution(self, entry: dict[str, Any]) -> None:
        _write(self._contrib_path, [*self.contributions(), entry])

    # --- sessions ----------------------------------------------------------------------

    @property
    def _sessions_dir(self) -> Path:
        return self.dir / "sessions"

    def new_session(self, member_id: str | None, description: str) -> Session:
        stamp = now_iso()
        session = Session(
            id=f"r-{uuid.uuid4().hex[:8]}",
            member_id=member_id,
            description=description,
            created_at=stamp,
            updated_at=stamp,
        )
        self.save_session(session)
        return session

    def save_session(self, session: Session) -> None:
        session.updated_at = now_iso()
        _write(self._sessions_dir / f"{session.id}.json", session.model_dump(mode="json"))

    def load_session(self, session_id: str) -> Session | None:
        path = self._sessions_dir / f"{Path(session_id).name}.json"
        if not path.exists():
            return None
        return Session.model_validate(_read(path))

    def active_session(self) -> Session | None:
        """Most recently touched session that is not finished."""
        if not self._sessions_dir.exists():
            return None
        live = [
            s
            for s in (Session.model_validate(_read(p)) for p in self._sessions_dir.glob("r-*.json"))
            if s.state not in TERMINAL_STATES
        ]
        return max(live, key=lambda s: s.updated_at, default=None)

    def latest_session(self) -> Session | None:
        """Most recently touched session, finished or not."""
        if not self._sessions_dir.exists():
            return None
        sessions = [Session.model_validate(_read(p)) for p in self._sessions_dir.glob("r-*.json")]
        return max(sessions, key=lambda s: s.updated_at, default=None)
