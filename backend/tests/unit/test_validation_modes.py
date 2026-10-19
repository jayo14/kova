"""Unit tests for the 5 first-class validation modes and their runner dispatch."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.flows.dependency_resolver import ExecutionPlan
from app.modules.validation.exploratory_runner import ExploratoryRunner
from app.modules.validation.functional_runner import FunctionalRunner
from app.modules.validation.models import ValidationMode
from app.modules.validation.regression_runner import RegressionRunner
from app.modules.validation.runner import ValidationRunner
from app.modules.validation.schemas import (
    ImpactReport,
    ValidationRequest,
)
from app.modules.validation.success_criteria import (
    SUCCESS_CRITERIA,
    SuccessCriteria,
)
from app.modules.validation.visual_runner import VisualRunner
from app.modules.validation.workflow_runner import WorkflowRunner


def test_each_mode_has_success_criteria():
    """Assert all 5 validation modes are defined in SUCCESS_CRITERIA with proper criteria."""
    expected_modes = {
        ValidationMode.FUNCTIONAL,
        ValidationMode.WORKFLOW,
        ValidationMode.REGRESSION,
        ValidationMode.EXPLORATORY,
        ValidationMode.VISUAL,
    }
    assert set(SUCCESS_CRITERIA.keys()) == expected_modes

    for mode in expected_modes:
        criteria = SUCCESS_CRITERIA[mode]
        assert isinstance(criteria, SuccessCriteria)
        assert criteria.mode == mode
        assert criteria.max_duration_seconds > 0
        assert criteria.max_turns > 0

    # Distinct criteria validation
    assert "state_transition" in SUCCESS_CRITERIA[ValidationMode.FUNCTIONAL].required_assertions
    assert "network_success" in SUCCESS_CRITERIA[ValidationMode.FUNCTIONAL].optional_assertions
    assert "persistence_after_reload" in SUCCESS_CRITERIA[ValidationMode.WORKFLOW].optional_assertions
    assert "downstream_effect" in SUCCESS_CRITERIA[ValidationMode.WORKFLOW].required_assertions
    assert "baseline_match" in SUCCESS_CRITERIA[ValidationMode.REGRESSION].required_assertions
    assert SUCCESS_CRITERIA[ValidationMode.EXPLORATORY].failure_tolerance == "investigative"
    assert SUCCESS_CRITERIA[ValidationMode.EXPLORATORY].max_turns == 80
    assert "visual_reference_match" in SUCCESS_CRITERIA[ValidationMode.VISUAL].required_assertions


@pytest.mark.asyncio
async def test_functional_runner_fails_on_network_error():
    """Functional validation runner catches HTTP >= 400 network errors as failure."""
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        mode=ValidationMode.FUNCTIONAL,
    )
    mock_network_response = MagicMock(status=500, status_code=500)

    runner = FunctionalRunner()
    report = await runner.run(req, network_response=mock_network_response)

    assert report.overall_status == "failed"
    assert report.failure_reason is not None
    assert "500" in report.failure_reason

    # Also test via ValidationRunner dispatch
    v_runner = ValidationRunner()
    dispatched_report = await v_runner.run(req, network_response=mock_network_response)
    assert dispatched_report.overall_status == "failed"
    assert "500" in (dispatched_report.failure_reason or "")


@pytest.mark.asyncio
async def test_workflow_runner_checks_persistence_after_reload():
    """Workflow validation reloads the page and checks state persistence across reload."""
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        mode=ValidationMode.WORKFLOW,
    )

    # 1. Successful persistence
    passing_browser = MagicMock()
    passing_browser.reload = AsyncMock()
    passing_browser.check_persistence = AsyncMock(return_value=True)

    runner = WorkflowRunner()
    pass_report = await runner.run(req, browser=passing_browser)
    assert pass_report.overall_status == "passed"
    assert passing_browser.reload.called

    # 2. Failed persistence after reload
    failing_browser = MagicMock()
    failing_browser.reload = AsyncMock()
    failing_browser.check_persistence = AsyncMock(return_value=False)

    fail_report = await runner.run(req, browser=failing_browser)
    assert fail_report.overall_status == "failed"
    assert "persist" in fail_report.failure_reason.lower()


@pytest.mark.asyncio
async def test_regression_runner_compares_baseline():
    """Regression runner compares execution against baseline and fails on diff."""
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        mode=ValidationMode.REGRESSION,
    )
    runner = RegressionRunner()

    baseline_data = b"image_hash_baseline"
    same_data = b"image_hash_baseline"
    diff_data = b"image_hash_altered_ui"

    # Case A: Identical baseline
    match_report = await runner.run(
        req,
        baseline_screenshot=baseline_data,
        current_screenshot=same_data,
    )
    assert match_report.overall_status == "passed"

    # Case B: Regression diff detected
    diff_report = await runner.run(
        req,
        baseline_screenshot=baseline_data,
        current_screenshot=diff_data,
    )
    assert diff_report.overall_status == "failed"
    assert "diff detected" in (diff_report.failure_reason or "").lower()


@pytest.mark.asyncio
async def test_exploratory_runner_counts_defect_as_success():
    """Exploratory runner uses agent loop to uncover unexpected behaviors; defects count as success."""
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        mode=ValidationMode.EXPLORATORY,
    )

    emitted_events = []

    def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    runner = ExploratoryRunner()
    report = await runner.run(
        req,
        discovered_defects=[{"defect": "Unhandled 500 on form submit"}],
        event_emitter=mock_emitter,
    )

    assert report.overall_status == "passed"
    assert report.discoveries == 1
    assert any(ev[0] == "defect_discovered" for ev in emitted_events)

    # Test via mock AgentExecutor outcome
    mock_agent = MagicMock()
    mock_outcome = MagicMock()
    mock_outcome.status = "FAILED"
    mock_outcome.reason = "Uncaught client exception when clicking tab"
    mock_outcome.failure_category = "defect"
    mock_outcome.verification = {}
    mock_outcome.discoveries = 1
    mock_agent.run = AsyncMock(return_value=mock_outcome)

    agent_report = await runner.run(
        req,
        agent_executor=mock_agent,
    )
    assert agent_report.overall_status == "passed"
    assert agent_report.discoveries >= 1


@pytest.mark.asyncio
async def test_visual_runner_stub_returns_unverified():
    """Visual runner stub returns unverified pointing to action 10."""
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        mode=ValidationMode.VISUAL,
    )
    runner = VisualRunner()
    report = await runner.run(req)

    assert report.overall_status == "unverified"
    assert "action 10" in report.failure_reason.lower()
