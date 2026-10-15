import uuid
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import pytest

from app.engine.execution.runner import FlowRunner
from app.engine.browser.session import BrowserSession
from app.engine.ai.schemas import JourneyPlan, ProposedStep
from app.engine.ai.settings import AISettings


@pytest.mark.asyncio
async def test_runner_dynamic_journey_planning_when_steps_empty():
    """Verify runner dynamically plans actions when flow_steps is empty but objective is set."""
    runner = FlowRunner()
    mock_plan = JourneyPlan(
        objective="Practice Quiz",
        intent="practice_quiz",
        steps=[
            ProposedStep(
                action="wait",
                description="Wait for quiz elements",
                target={"css": "body"},
            )
        ],
        success_condition={"text_visible": "Quiz Completed"},
        confidence=0.9,
    )

    with patch("app.engine.execution.runner.publish_frame", return_value=None):
        with patch.object(BrowserSession, "navigate", return_value=None):
            with patch.object(BrowserSession, "close", return_value=None):
                with patch("app.engine.ai.reasoner.AgentReasoner.plan_journey", return_value=mock_plan):
                    with patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True):
                        with patch("app.engine.ai.provider.get_ai_provider", return_value=MagicMock()):
                            result = await runner.execute(
                                execution_id=uuid.uuid4(),
                                flow_steps=[],
                                target_url="https://example.com/quiz",
                                objective="Practice Quiz",
                                success_condition=None,
                            )
                            assert result is not None
                            assert "events" in result


def _build_mock_browser():
    mb = AsyncMock()
    mb.page = AsyncMock()
    mb.page.url = "https://example.com"
    mb.page.title = AsyncMock(return_value="Example")
    mb.page.on = MagicMock()
    mb.page.remove_listener = MagicMock()
    mb.page.context.cookies = AsyncMock(return_value=[])
    mb.page.context.add_cookies = AsyncMock()
    mb.network_errors = []
    mb.start = AsyncMock()
    mb.close = AsyncMock()
    mb.navigate = AsyncMock()
    return mb


@pytest.mark.asyncio
async def test_runner_plans_and_goes_straight_to_running_when_no_prerequisites():
    """Target flow with no prerequisites plans instantly and transitions to RUNNING without resolving prerequisites."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.modules.flows.schemas import FlowStateContract
    from app.modules.executions.event_types import EventTypes

    runner = FlowRunner()
    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Independent Flow",
        steps=[{"type": "wait", "value": "50"}],
        state_contract=FlowStateContract(),
        success_condition={"text_visible": "Done"},
    )

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:
        from app.engine.verification.verifier import VerificationResult
        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        events = []
        async def recorder(eid, etype, payload):
            events.append(etype)

        result = await runner.run(
            execution_id=uuid.uuid4(),
            target_flow=target_flow,
            event_recorder=recorder,
        )

        assert result["success"] is True
        assert EventTypes.EXECUTION_PLANNED in events
        assert EventTypes.PREREQUISITE_RESOLVED not in events
        assert EventTypes.EXECUTION_STARTED in events
        assert result["current_state"] is not None


@pytest.mark.asyncio
async def test_runner_resolves_auth_prerequisite_via_session_manager():
    """Target flow requiring auth enters RESOLVING_PREREQUISITES and calls SessionManager."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.modules.flows.schemas import FlowStateContract, StateAssertion
    from app.modules.executions.event_types import EventTypes
    from app.modules.flows.auth import SessionManager
    from app.engine.browser.session import SessionState

    runner = FlowRunner()
    auth_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="auth_student",
        persona="student",
        steps=[],
        state_contract=FlowStateContract(
            persona="student",
            produces=[StateAssertion(key="authenticated:student", value=True)],
        ),
    )
    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Submit Assignment",
        persona="student",
        steps=[{"type": "wait", "value": "50"}],
        state_contract=FlowStateContract(
            persona="student",
            requires=[StateAssertion(key="authenticated:student", value=True)],
        ),
        success_condition={"text_visible": "Submitted"},
    )

    mock_session_mgr = MagicMock(spec=SessionManager)
    mock_session_mgr.get_or_establish = AsyncMock(
        return_value=(SessionState(cookies=[{"name": "sess", "value": "123"}]), False)
    )

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:
        from app.engine.verification.verifier import VerificationResult
        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        events = []
        async def recorder(eid, etype, payload):
            events.append(etype)

        result = await runner.run(
            execution_id=uuid.uuid4(),
            target_flow=target_flow,
            flows=[auth_flow, target_flow],
            persona="student",
            session_manager=mock_session_mgr,
            event_recorder=recorder,
        )

        assert result["success"] is True
        assert EventTypes.EXECUTION_PLANNED in events
        assert EventTypes.PREREQUISITE_RESOLVED in events
        assert mock_session_mgr.get_or_establish.call_count == 1
        assert result["current_state"].get("authenticated:student") is True


@pytest.mark.asyncio
async def test_runner_unsatisfiable_prerequisite_fails_closed():
    """Unsatisfiable prerequisite immediately stops execution, emits PREREQUISITE_FAILED, and returns UNVERIFIED."""
    from types import SimpleNamespace
    from app.modules.flows.schemas import FlowStateContract, StateAssertion
    from app.modules.executions.event_types import EventTypes

    runner = FlowRunner()
    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Secret Flow",
        steps=[{"type": "click", "target": "#secret"}],
        state_contract=FlowStateContract(
            requires=[StateAssertion(key="role:admin", value=True)],
        ),
        success_condition={"text_visible": "Admin Page"},
    )

    events = []
    async def recorder(eid, etype, payload):
        events.append(etype)

    result = await runner.run(
        execution_id=uuid.uuid4(),
        target_flow=target_flow,
        flows=[target_flow],
        event_recorder=recorder,
    )

    assert result["success"] is False
    assert result["error_code"] == "PREREQUISITE_FAILED"
    assert result["state"] == "UNVERIFIED"
    assert "role:admin" in result["unresolved"]
    assert EventTypes.EXECUTION_PLANNED in events
    assert EventTypes.PREREQUISITE_FAILED in events


@pytest.mark.asyncio
async def test_runner_contamination_detected_invokes_reset_strategy():
    """Contamination detected mid-planning/execution invokes reset strategy and emits STATE_CONTAMINATED and STATE_RESET."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.modules.flows.schemas import FlowStateContract, StateAssertion
    from app.modules.executions.event_types import EventTypes

    runner = FlowRunner()
    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Mutating Flow",
        steps=[
            {"type": "wait", "value": "50", "mutates": ["assignment.status"]},
            {"type": "wait", "value": "50", "requires": ["assignment.status"]},
        ],
        state_contract=FlowStateContract(
            requires=[StateAssertion(key="assignment.status", value="draft")],
            mutates=["assignment.status"],
            reset_strategy="re_establish",
        ),
        success_condition={"text_visible": "Submitted"},
    )

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:
        from app.engine.verification.verifier import VerificationResult
        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        events = []
        async def recorder(eid, etype, payload):
            events.append(etype)

        result = await runner.run(
            execution_id=uuid.uuid4(),
            target_flow=target_flow,
            current_state={"assignment.status": "draft"},
            event_recorder=recorder,
        )

        assert EventTypes.STATE_CONTAMINATED in events
        assert EventTypes.STATE_RESET in events

