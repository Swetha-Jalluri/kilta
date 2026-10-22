import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from kilta.data import DataStore
from kilta.engine import Engine

REPO_DATA = Path(__file__).resolve().parents[2] / "data"
TODAY = date(2026, 10, 21)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A throwaway copy of the fictional data, so tests never touch runtime state."""
    target = tmp_path / "data"
    shutil.copytree(REPO_DATA, target, ignore=shutil.ignore_patterns("sessions", "state"))
    return target


@pytest.fixture
def store(data_dir: Path) -> DataStore:
    return DataStore(data_dir)


@pytest.fixture
def engine(store: DataStore) -> Engine:
    return Engine(store, today=lambda: TODAY)


def edit_json(path: Path, change) -> None:
    payload = json.loads(path.read_text())
    change(payload)
    path.write_text(json.dumps(payload))


def to_quick_checks(
    engine: Engine,
    appliance_id: str = "dishwasher",
    member: str = "priya",
    description: str = "it is beeping and there is water at the bottom",
):
    """Drive the engine through safety, identify and manual. Returns the session id."""
    sid = engine.start_repair(member, description).session.id
    engine.safety_check(sid, danger_reported=False)
    engine.identify_appliance(sid, appliance_id=appliance_id)
    engine.find_manual(sid)
    engine.quick_checks(sid)
    return sid


def to_prepare(
    engine: Engine, code: str = "E24", appliance_id: str = "dishwasher", member: str = "priya"
):
    sid = to_quick_checks(engine, appliance_id, member)
    out = engine.diagnose(sid, error_code=code)
    return sid, out
