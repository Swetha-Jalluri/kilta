import json

import pytest
from pydantic import ValidationError

from kilta.models import Manual
from tests.conftest import REPO_DATA


def load(name: str) -> dict:
    return json.loads((REPO_DATA / "manuals" / f"{name}.json").read_text())


@pytest.mark.parametrize("name", ["kelvara-dw300", "kelvara-wm500"])
def test_every_step_cites_manual_and_page(name):
    manual = Manual.model_validate(load(name))
    steps = [s for p in manual.procedures for s in p.steps]
    assert steps
    for step in steps:
        assert step.source.manual_id == manual.id
        assert step.source.page >= 1


def test_step_without_source_fails_validation():
    raw = load("kelvara-dw300")
    del raw["procedures"][0]["steps"][0]["source"]
    with pytest.raises(ValidationError, match="source"):
        Manual.model_validate(raw)


def test_step_with_page_zero_fails_validation():
    raw = load("kelvara-dw300")
    raw["procedures"][0]["steps"][0]["source"]["page"] = 0
    with pytest.raises(ValidationError):
        Manual.model_validate(raw)


def test_step_citing_another_manual_fails_validation():
    raw = load("kelvara-dw300")
    raw["procedures"][0]["steps"][0]["source"]["manual_id"] = "kelvara-wm500"
    with pytest.raises(ValidationError, match="inside manual"):
        Manual.model_validate(raw)


def test_technician_only_code_cannot_have_diy_procedure():
    raw = load("kelvara-dw300")
    raw["error_codes"][1]["procedure_ids"] = ["clean-filter"]
    with pytest.raises(ValidationError, match="technician-only"):
        Manual.model_validate(raw)


def test_panel_labels_and_gate_prompt_are_separate_fields():
    manual = Manual.model_validate(load("kelvara-dw300"))
    steps = manual.procedure("clean-filter").steps
    assert steps[0].gate and steps[0].gate.prompt == "Is the dishwasher unplugged?"
    assert steps[-1].panel_labels == ["Rinse"]
