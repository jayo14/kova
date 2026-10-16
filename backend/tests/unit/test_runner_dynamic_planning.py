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
    mb.page.screenshot = AsyncMock(return_value=b"pngdata")
    mb.page.evaluate = AsyncMock(return_value="")
    mb.page.on = MagicMock()
    mb.page.remove_listener = MagicMock()
    mb.page.context.cookies = AsyncMock(return_value=[])
    mb.page.context.add_cookies = AsyncMock()
    mb.get_dom_snapshot = AsyncMock(return_value="<html></html>")
    mb.get_a11y_tree = AsyncMock(return_value={})
    mb.observe = AsyncMock(return_value={"url": "https://example.com", "interactive_elements": []})
    mb.network_errors = []
    mb.start = AsyncMock()
    mb.close = AsyncMock()
    mb.navigate = AsyncMock()
    return mb


def _build_mock_ai_provider():
    p = AsyncMock()
    p.generate_structured = AsyncMock()
    p.generate_json = AsyncMock(return_value={})
    p.generate_text = AsyncMock(return_value="")
    return p


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


@pytest.mark.asyncio
async def test_dynamic_planning_validates_each_step():
    """Verify each AI-proposed step is validated and rejected steps emit AI_PROPOSAL_REJECTED."""
    from app.modules.executions.event_types import EventTypes
    from app.engine.verification.verifier import VerificationResult

    runner = FlowRunner()
    mock_plan = JourneyPlan(
        objective="Navigate flows",
        intent="nav_intent",
        steps=[
            ProposedStep(
                action="navigate",
                description="Valid navigation",
                value="https://example.com/valid",
                target={"css": "body"},
            ),
            ProposedStep(
                action="navigate",
                description="Forbidden navigation",
                value="http://attacker.com/evil",
                target={"css": "body"},
            ),
        ],
        success_condition={"url_contains": "/valid"},
        confidence=0.9,
    )

    events = []
    event_payloads = []

    async def recorder(eid, etype, payload):
        events.append(etype)
        event_payloads.append((etype, payload))

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.ai.reasoner.AgentReasoner.plan_journey", return_value=mock_plan), \
         patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True), \
         patch("app.engine.ai.provider.get_ai_provider", return_value=_build_mock_ai_provider()), \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        result = await runner.execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="https://example.com",
            objective="Navigate flows",
            event_recorder=recorder,
        )

        assert result is not None
        assert EventTypes.AI_PROPOSAL_REJECTED in events
        rejection_events = [p for etype, p in event_payloads if etype == EventTypes.AI_PROPOSAL_REJECTED]
        assert len(rejection_events) == 1
        assert rejection_events[0]["count"] == 1
        assert "attacker.com" in rejection_events[0]["reasons"][0]["reason"]


@pytest.mark.asyncio
async def test_dynamic_planning_unverified_when_all_steps_rejected():
    """Verify execution ends UNVERIFIED when all AI-proposed steps fail validation."""
    from app.modules.executions.event_types import EventTypes

    runner = FlowRunner()
    mock_plan = JourneyPlan(
        objective="All forbidden",
        intent="forbidden_intent",
        steps=[
            ProposedStep(
                action="navigate",
                description="Forbidden 1",
                value="http://attacker.com/evil1",
                target={"css": "body"},
            ),
            ProposedStep(
                action="navigate",
                description="Forbidden 2",
                value="http://attacker.com/evil2",
                target={"css": "body"},
            ),
        ],
        success_condition={"url_contains": "/evil"},
        confidence=0.8,
    )

    events = []

    async def recorder(eid, etype, payload):
        events.append(etype)

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.ai.reasoner.AgentReasoner.plan_journey", return_value=mock_plan), \
         patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True), \
         patch("app.engine.ai.provider.get_ai_provider", return_value=_build_mock_ai_provider()):

        result = await runner.execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="https://example.com",
            objective="All forbidden",
            event_recorder=recorder,
        )

        assert result["success"] is False
        assert result["error_code"] == "UNVERIFIED"
        assert result["failure_category"] == "ai_proposal_rejected"
        assert EventTypes.AI_PROPOSAL_ALL_REJECTED in events


@pytest.mark.asyncio
async def test_dynamic_planning_preserves_success_condition():
    """Verify dynamic plan's success_condition is preserved and passed to verifier."""
    from app.engine.verification.verifier import VerificationResult

    runner = FlowRunner()
    mock_plan = JourneyPlan(
        objective="Valid goal",
        intent="valid_intent",
        steps=[
            ProposedStep(
                action="wait",
                description="Wait for element",
                value="100",
                target={"css": "body"},
            )
        ],
        success_condition={"text_visible": "Dashboard Ready"},
        confidence=0.9,
    )

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.ai.reasoner.AgentReasoner.plan_journey", return_value=mock_plan), \
         patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True), \
         patch("app.engine.ai.provider.get_ai_provider", return_value=_build_mock_ai_provider()), \
         patch("app.engine.execution.runner.Verifier.verify", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = VerificationResult(passed=True, checks=[])

        result = await runner.execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="https://example.com",
            objective="Valid goal",
            success_condition=None,
        )

        assert result is not None
        assert mock_verify.called
        call_condition = mock_verify.call_args[0][0]
        assert call_condition == {"text_visible": "Dashboard Ready"}


@pytest.mark.asyncio
async def test_dynamic_planning_rejects_credential_in_value():
    """Verify dynamic plan rejects steps with credential pattern in literal value."""
    from app.modules.executions.event_types import EventTypes

    runner = FlowRunner()
    mock_plan = JourneyPlan(
        objective="Login goal",
        intent="login_intent",
        steps=[
            ProposedStep(
                action="type",
                description="Type password literal",
                value="password:supersecret123",
                target={"css": "#password"},
            )
        ],
        success_condition={"text_visible": "Welcome"},
        confidence=0.85,
    )

    events = []
    event_payloads = []

    async def recorder(eid, etype, payload):
        events.append(etype)
        event_payloads.append((etype, payload))

    with patch("app.engine.execution.runner.BrowserSession", return_value=_build_mock_browser()), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.ai.reasoner.AgentReasoner.plan_journey", return_value=mock_plan), \
         patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True), \
         patch("app.engine.ai.provider.get_ai_provider", return_value=_build_mock_ai_provider()):

        result = await runner.execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="https://example.com",
            objective="Login goal",
            event_recorder=recorder,
        )

        assert result["success"] is False
        assert result["error_code"] == "UNVERIFIED"
        assert EventTypes.AI_PROPOSAL_REJECTED in events
        rejection_events = [p for etype, p in event_payloads if etype == EventTypes.AI_PROPOSAL_REJECTED]
        assert "credential" in rejection_events[0]["reasons"][0]["reason"].lower() or "secret" in rejection_events[0]["reasons"][0]["reason"].lower()

