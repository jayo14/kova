"""Unit tests for AI test maintenance (§5 capability F + §4 Stage 8)."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import ScenarioValidityAssessment
from app.engine.ai.test_maintainer import TestMaintainer


@pytest.mark.asyncio
async def test_maintainer_marks_flow_stale_when_locator_missing():
    flow_id = uuid.uuid4()
    mock_flow = MagicMock()
    mock_flow.id = flow_id
    mock_flow.objective = "Submit contact form"
    mock_flow.success_condition = {"text_visible": "Thank you"}
    mock_flow.steps = [{"type": "click", "target": "#submit-btn", "description": "Submit form"}]
    mock_flow.last_validated_against_graph_version = 1

    mock_flow_repo = MagicMock()
    mock_flow_repo.get_by_id = AsyncMock(return_value=mock_flow)
    mock_flow_repo.update = AsyncMock()

    # Heuristic reasoner (provider is None)
    reasoner = AgentReasoner(provider=None)
    maintainer = TestMaintainer(reasoner=reasoner, flow_repo=mock_flow_repo)

    # New page state where locator #submit-btn is missing
    new_page_state = {
        "url": "/contact",
        "buttons": [{"name": "Send Message", "selector": "#send-message-btn"}],
        "locator_matches": [{"original_target": "#other-btn", "current_target": "#other-btn"}],
    }

    assessment = await maintainer.evaluate_stale_flow(flow_id, new_page_state=new_page_state)

    assert assessment.is_still_valid is False
    assert assessment.requires_review is True
    assert len(assessment.changes_detected) > 0
    assert "#submit-btn" in assessment.changes_detected[0]

    mock_flow_repo.update.assert_called_once()
    call_args = mock_flow_repo.update.call_args[0][1]
    assert call_args["requires_review"] is True
    assert call_args["stale_reason"] is not None


@pytest.mark.asyncio
async def test_maintainer_confirms_valid_when_locators_intact():
    flow_id = uuid.uuid4()
    mock_flow = MagicMock()
    mock_flow.id = flow_id
    mock_flow.objective = "Login"
    mock_flow.success_condition = {"url_matches": "/dashboard"}
    mock_flow.steps = [{"type": "click", "target": "#login-btn"}]
    mock_flow.last_validated_against_graph_version = 1

    mock_flow_repo = MagicMock()
    mock_flow_repo.get_by_id = AsyncMock(return_value=mock_flow)
    mock_flow_repo.update = AsyncMock()

    reasoner = AgentReasoner(provider=None)
    maintainer = TestMaintainer(reasoner=reasoner, flow_repo=mock_flow_repo)

    new_page_state = {
        "url": "/login",
        "locator_matches": [{"original_target": "#login-btn", "current_target": "#login-btn"}],
    }

    assessment = await maintainer.evaluate_stale_flow(flow_id, new_page_state=new_page_state)

    assert assessment.is_still_valid is True
    assert assessment.requires_review is False
    call_args = mock_flow_repo.update.call_args[0][1]
    assert call_args["requires_review"] is False
    assert call_args["stale_reason"] is None


@pytest.mark.asyncio
async def test_maintainer_never_modifies_success_condition():
    flow_id = uuid.uuid4()
    mock_flow = MagicMock()
    mock_flow.id = flow_id
    mock_flow.objective = "Checkout"
    initial_condition = {"url_matches": "/order-confirmed", "text_visible": "Order Placed"}
    mock_flow.success_condition = initial_condition
    mock_flow.steps = [{"type": "click", "target": "#buy-now"}]
    mock_flow.last_validated_against_graph_version = 2

    mock_flow_repo = MagicMock()
    mock_flow_repo.get_by_id = AsyncMock(return_value=mock_flow)
    mock_flow_repo.update = AsyncMock()

    reasoner = AgentReasoner(provider=None)
    maintainer = TestMaintainer(reasoner=reasoner, flow_repo=mock_flow_repo)

    await maintainer.evaluate_stale_flow(flow_id, new_page_state={"locator_matches": []})

    call_args = mock_flow_repo.update.call_args[0][1]
    # success_condition must never be altered or updated
    assert "success_condition" not in call_args
    assert mock_flow.success_condition == initial_condition


@pytest.mark.asyncio
async def test_heuristic_fallback_when_ai_disabled():
    reasoner = AgentReasoner(provider=None)
    flow = {
        "id": "flow_123",
        "objective": "Test",
        "success_condition": {"status": "ok"},
        "steps": [{"type": "click", "target": "#missing-btn"}],
    }
    assessment = await reasoner.evaluate_scenario_validity(
        flow=flow,
        new_page_state={"locator_matches": [{"original_target": "#other"}]},
        original_graph_version=1,
    )

    assert assessment.confidence == 0.5
    assert assessment.requires_review is True
    assert "missing locators detected" in assessment.reasoning


@pytest.mark.asyncio
async def test_proposed_locator_updates_not_auto_applied():
    flow_id = uuid.uuid4()
    mock_flow = MagicMock()
    mock_flow.id = flow_id
    original_steps = [{"type": "click", "target": "#old-button"}]
    mock_flow.steps = original_steps
    mock_flow.objective = "Settings"
    mock_flow.success_condition = {}
    mock_flow.last_validated_against_graph_version = 1

    mock_flow_repo = MagicMock()
    mock_flow_repo.get_by_id = AsyncMock(return_value=mock_flow)
    mock_flow_repo.update = AsyncMock()

    mock_provider = MagicMock()
    mock_assessment = ScenarioValidityAssessment(
        flow_id=str(flow_id),
        is_still_valid=True,
        confidence=0.9,
        changes_detected=["Button ID changed"],
        requires_review=True,
        proposed_locator_updates=[{"step_index": 0, "new_selector": "#new-button"}],
        reasoning="Button updated to #new-button",
    )
    mock_provider.generate_structured = AsyncMock(return_value=mock_assessment)

    reasoner = AgentReasoner(mock_provider)
    maintainer = TestMaintainer(reasoner=reasoner, flow_repo=mock_flow_repo)

    assessment = await maintainer.evaluate_stale_flow(flow_id, new_page_state={})

    assert len(assessment.proposed_locator_updates) == 1
    # Flow steps must remain unchanged; updates are proposals in the assessment only
    call_args = mock_flow_repo.update.call_args[0][1]
    assert "steps" not in call_args
    assert mock_flow.steps == original_steps
