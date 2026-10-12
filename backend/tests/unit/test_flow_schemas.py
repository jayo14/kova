import pytest
from pydantic import ValidationError

from app.modules.flows.schemas import FlowCreate


def test_flow_step_rejects_click_without_target():
    with pytest.raises(ValidationError, match="requires an element target"):
        FlowCreate.model_validate({"project_id": "00000000-0000-0000-0000-000000000001", "name": "Bad", "steps": [{"action": "click"}]})


def test_flow_step_preserves_structured_targets_and_navigation_url():
    flow = FlowCreate.model_validate({
        "project_id": "00000000-0000-0000-0000-000000000001",
        "name": "Good",
        "steps": [
            {"action": "click", "target": {"role": "button", "name": "Save"}, "wait_for": "visible"},
            {"action": "navigate", "url": "https://example.test/home"},
        ],
    })
    steps = [step.model_dump() for step in flow.steps]
    assert steps[0]["target"] == {"role": "button", "name": "Save"}
    assert steps[0]["wait_for"] == "visible"
    assert steps[1]["url"] == "https://example.test/home"


def test_flow_rejects_duplicate_step_ids():
    with pytest.raises(ValidationError, match="step_id values must be unique"):
        FlowCreate.model_validate({
            "project_id": "00000000-0000-0000-0000-000000000001",
            "name": "Duplicate IDs",
            "steps": [
                {"step_id": "same", "action": "navigate", "url": "https://example.test/"},
                {"step_id": "same", "action": "navigate", "url": "https://example.test/other"},
            ],
        })
