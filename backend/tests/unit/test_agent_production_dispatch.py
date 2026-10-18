import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import pytest

from app.config.settings import settings
from app.engine.ai.executor import AgentExecutor, AgentOutcome
from app.engine.ai.settings import AISettings
from app.engine.execution.context import ExecutionState
from app.engine.execution.runner import FlowRunner
from app.engine.verification.verifier import VerificationResult
from app.modules.executions.event_types import EventTypes
from app.modules.flows.schemas import FlowStateContract


def _build_mock_browser():
    mb = AsyncMock()
    mb.page = AsyncMock()
    mb.page.url = "https://example.com"
    mb.page.title = AsyncMock(return_value="Example App")
    mb.page.screenshot = AsyncMock(return_value=b"pngdata")
    mb.page.evaluate = AsyncMock(return_value="Page content")
    mb.page.on = MagicMock()
    mb.page.remove_listener = MagicMock()
    mb.page.is_closed = MagicMock(return_value=False)
    mb.page.context.cookies = AsyncMock(return_value=[])
    mb.page.context.add_cookies = AsyncMock()
    mb.get_dom_snapshot = AsyncMock(return_value="<html><body>Example</body></html>")
    mb.get_a11y_tree = AsyncMock(return_value={})
    mb.observe = AsyncMock(return_value={"url": "https://example.com", "interactive_elements": []})
    mb.network_errors = []
    mb.start = AsyncMock()
    mb.close = AsyncMock()
    mb.navigate = AsyncMock()
    mb.start_step_network_capture = MagicMock()
    mb.end_step_network_capture = MagicMock(return_value=[])
    mb.video_path = None
    mb.trace_path = None
    return mb


@pytest.mark.asyncio
async def test_agent_loop_dispatched_when_flag_on_and_no_steps(monkeypatch):
    """Flow with objective but no steps dispatches to AgentExecutor.run when feature flag is ON."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", True)

    runner = FlowRunner()
    exec_id = uuid.uuid4()
    target_flow = SimpleNamespace(
        id=exec_id,
        name="Agent Flow",
        objective="Create a new workspace",
        steps=[],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Workspace Created"},
    )

    mock_outcome = AgentOutcome(
        status="COMPLETED",
        reason="Target objective achieved",
        facts=["Workspace named Alpha created"],
    )

    mock_browser = _build_mock_browser()

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.browser.evidence_storage.EvidenceStorage.upload_file", return_value=None), \
         patch.object(AgentExecutor, "run", new_callable=AsyncMock) as mock_agent_run, \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:

        mock_agent_run.return_value = mock_outcome
        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        result = await runner.execute(
            execution_id=exec_id,
            target_flow=target_flow,
            flow_steps=[],
            target_url="https://example.com/app",
            objective="Create a new workspace",
            success_condition={"text_visible": "Workspace Created"},
        )

        assert mock_agent_run.called, "AgentExecutor.run should have been invoked"
        assert result["success"] is True
        assert result["state"] == ExecutionState.COMPLETED.value

        event_types = [e["type"] for e in result["events"]]
        assert EventTypes.AGENT_LOOP_STARTED in event_types
        assert EventTypes.AGENT_LOOP_OUTCOME in event_types


@pytest.mark.asyncio
async def test_deterministic_runner_used_when_steps_present(monkeypatch):
    """Flow with pre-baked steps does NOT dispatch to AgentExecutor even if flag is ON."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", True)

    runner = FlowRunner()
    exec_id = uuid.uuid4()
    target_flow = SimpleNamespace(
        id=exec_id,
        name="Step Flow",
        objective="Fill form",
        steps=[{"type": "wait", "value": "50"}],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Saved"},
    )

    mock_browser = _build_mock_browser()

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.browser.evidence_storage.EvidenceStorage.upload_file", return_value=None), \
         patch.object(AgentExecutor, "run", new_callable=AsyncMock) as mock_agent_run, \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:

        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        result = await runner.execute(
            execution_id=exec_id,
            target_flow=target_flow,
            flow_steps=[{"type": "wait", "value": "50"}],
            target_url="https://example.com",
            objective="Fill form",
            success_condition={"text_visible": "Saved"},
        )

        assert not mock_agent_run.called, "AgentExecutor.run should NOT be called when steps exist"
        assert result["success"] is True
        assert result["state"] == ExecutionState.COMPLETED.value


@pytest.mark.asyncio
async def test_deterministic_runner_used_when_flag_off(monkeypatch):
    """Flow with objective but no steps terminates UNVERIFIED when feature flag is OFF."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", False)

    runner = FlowRunner()
    exec_id = uuid.uuid4()
    target_flow = SimpleNamespace(
        id=exec_id,
        name="Agent Flow",
        objective="Create account",
        steps=[],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Success"},
    )

    mock_browser = _build_mock_browser()

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=False), \
         patch.object(AgentExecutor, "run", new_callable=AsyncMock) as mock_agent_run:

        result = await runner.execute(
            execution_id=exec_id,
            target_flow=target_flow,
            flow_steps=[],
            target_url="https://example.com",
            objective="Create account",
            success_condition={"text_visible": "Success"},
        )

        assert not mock_agent_run.called, "AgentExecutor.run must NOT be called when flag is OFF"
        assert result["success"] is False
        assert result["state"] == ExecutionState.UNVERIFIED.value
        assert result["failure_category"] == "no_steps_no_agent"


@pytest.mark.asyncio
async def test_agent_completion_requires_verifier_pass(monkeypatch):
    """AgentOutcome.COMPLETED must be verified by Verifier. If verifier fails, state is UNVERIFIED."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", True)

    runner = FlowRunner()
    exec_id = uuid.uuid4()
    target_flow = SimpleNamespace(
        id=exec_id,
        name="Agent Flow",
        objective="Buy item",
        steps=[],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Order Confirmed"},
    )

    mock_outcome = AgentOutcome(
        status="COMPLETED",
        reason="Agent claims order is placed",
    )

    mock_browser = _build_mock_browser()

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.browser.evidence_storage.EvidenceStorage.upload_file", return_value=None), \
         patch.object(AgentExecutor, "run", new_callable=AsyncMock) as mock_agent_run, \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:

        mock_agent_run.return_value = mock_outcome
        mock_verify.return_value = VerificationResult(passed=False, checks=[])

        result = await runner.execute(
            execution_id=exec_id,
            target_flow=target_flow,
            flow_steps=[],
            target_url="https://example.com",
            objective="Buy item",
            success_condition={"text_visible": "Order Confirmed"},
        )

        assert mock_agent_run.called
        assert result["success"] is False
        assert result["state"] == ExecutionState.UNVERIFIED.value
        assert result["failure_category"] == "verifier_rejected_agent_completion"


@pytest.mark.asyncio
async def test_agent_needs_input_transitions_to_paused(monkeypatch):
    """AgentOutcome.NEEDS_INPUT transitions to PAUSED with control_state='human'."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", True)

    runner = FlowRunner()
    exec_id = uuid.uuid4()
    target_flow = SimpleNamespace(
        id=exec_id,
        name="Agent Flow",
        objective="Login with 2FA",
        steps=[],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Dashboard"},
    )

    mock_outcome = AgentOutcome(
        status="NEEDS_INPUT",
        reason="2FA verification code required from authenticator app",
    )

    mock_browser = _build_mock_browser()

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.browser.evidence_storage.EvidenceStorage.upload_file", return_value=None), \
         patch.object(AgentExecutor, "run", new_callable=AsyncMock) as mock_agent_run:

        mock_agent_run.return_value = mock_outcome

        result = await runner.execute(
            execution_id=exec_id,
            target_flow=target_flow,
            flow_steps=[],
            target_url="https://example.com",
            objective="Login with 2FA",
            success_condition={"text_visible": "Dashboard"},
        )

        assert mock_agent_run.called
        assert result["success"] is False
        assert result["state"] == ExecutionState.PAUSED.value
        assert result["control_state"] == "human"
        assert "2FA verification code" in result["error"]


@pytest.mark.asyncio
async def test_agent_blocked_transitions_to_blocked(monkeypatch):
    """AgentOutcome.BLOCKED transitions to terminal BLOCKED with failure category."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", True)

    runner = FlowRunner()
    exec_id = uuid.uuid4()
    target_flow = SimpleNamespace(
        id=exec_id,
        name="Agent Flow",
        objective="Delete everything",
        steps=[],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Done"},
    )

    mock_outcome = AgentOutcome(
        status="BLOCKED",
        reason="Destructive action blocked by safety guardrails",
        failure_category="destructive_action_disallowed",
    )

    mock_browser = _build_mock_browser()

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.browser.evidence_storage.EvidenceStorage.upload_file", return_value=None), \
         patch.object(AgentExecutor, "run", new_callable=AsyncMock) as mock_agent_run:

        mock_agent_run.return_value = mock_outcome

        result = await runner.execute(
            execution_id=exec_id,
            target_flow=target_flow,
            flow_steps=[],
            target_url="https://example.com",
            objective="Delete everything",
            success_condition={"text_visible": "Done"},
        )

        assert mock_agent_run.called
        assert result["success"] is False
        assert result["state"] == ExecutionState.BLOCKED.value
        assert result["failure_category"] == "destructive_action_disallowed"
