import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.ai.executor import AgentExecutor
from app.engine.ai.schemas import ActionProposal
from app.engine.execution.context import ExecutionContext
from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState
from app.engine.safety.destructive_guard import DestructiveActionBlocked, DestructiveActionGuard
from app.modules.executions.event_types import EventTypes
from app.modules.projects.schemas import SafetyRestrictions


def test_guard_blocks_delete_user_action():
    guard = DestructiveActionGuard(SafetyRestrictions(destructive_action_allowlist=[]))
    with pytest.raises(DestructiveActionBlocked):
        guard.check(action_type="click", target_label="Delete user account", target_selector=None)


def test_guard_allows_when_in_allowlist():
    guard = DestructiveActionGuard(SafetyRestrictions(destructive_action_allowlist=["delete test user"]))
    # Should not raise
    guard.check(action_type="click", target_label="Delete test user", target_selector=None)


def test_guard_allows_non_destructive_actions():
    guard = DestructiveActionGuard(SafetyRestrictions(destructive_action_allowlist=[]))
    # Should not raise
    guard.check(action_type="click", target_label="Save changes", target_selector=None)
    guard.check(action_type="navigate", target_label=None, target_selector="/dashboard")


def test_guard_blocks_payment_action():
    guard = DestructiveActionGuard(SafetyRestrictions(destructive_action_allowlist=[]))
    with pytest.raises(DestructiveActionBlocked):
        guard.check(action_type="click", target_label="Pay $99 now", target_selector=None)


@pytest.mark.asyncio
async def test_runner_transitions_to_blocked_when_guard_raises():
    runner = FlowRunner()
    ctx = ExecutionContext(
        execution_id=str(uuid.uuid4()),
        target_url="https://example.com",
        safety_restrictions=SafetyRestrictions(destructive_action_allowlist=[]),
    )
    ctx.state = ExecutionState.RUNNING
    browser = MagicMock()
    browser.observe = AsyncMock(return_value={"url": "https://example.com", "interactive_elements": []})
    action_executor = MagicMock()

    destructive_step = {
        "step_id": "step_1",
        "action": "click",
        "target": {"css": "button.delete", "text": "Delete organization"},
        "label": "Delete organization",
    }

    recorded_events = []

    async def mock_event_recorder(event_type, payload):
        recorded_events.append((event_type, payload))

    with pytest.raises(Exception):
        await runner._execute_step(ctx, browser, action_executor, destructive_step, 0, mock_event_recorder)

    assert ctx.state == ExecutionState.BLOCKED
    event_types = [e["type"] for e in ctx.events]
    assert EventTypes.DESTRUCTIVE_ACTION_BLOCKED in event_types


@pytest.mark.asyncio
async def test_agent_loop_returns_blocked_when_guard_raises():
    reasoner = MagicMock()
    mock_goal = MagicMock(goal="Delete testing account", intent="delete", needs_account=False, needs_email_capability=False, risk_level="high")
    reasoner.interpret_goal = AsyncMock(return_value=mock_goal)
    mock_plan = MagicMock(objective="Delete testing account", steps=[], confidence=0.8, reasoning="Plan delete")
    reasoner.plan_journey = AsyncMock(return_value=mock_plan)

    # Reasoner proposes a destructive click
    proposal = ActionProposal(
        action="click",
        target={"css": "button.delete-acc", "text": "Permanently delete account"},
        value="",
        reason="Click delete account button to test user removal",
    )
    reasoner.propose_next_action = AsyncMock(return_value=proposal)

    recorded_events = []

    async def mock_emitter(event_type, payload):
        recorded_events.append((event_type, payload))

    executor = AgentExecutor(
        execution_id=uuid.uuid4(),
        reasoner=reasoner,
        email_provider=None,
        safety_restrictions=SafetyRestrictions(destructive_action_allowlist=[]),
        event_emitter=mock_emitter,
        max_turns=3,
    )

    browser = MagicMock()
    browser.navigate = AsyncMock()
    browser.page = MagicMock(url="https://example.com")
    browser.observe = AsyncMock(return_value={"url": "https://example.com", "interactive_elements": []})

    outcome = await executor.run(browser=browser, target_url="https://example.com", objective="Delete testing account")

    assert outcome.status == "BLOCKED"
    assert outcome.failure_category == "destructive_action_blocked"
    assert any(e[0] == EventTypes.DESTRUCTIVE_ACTION_BLOCKED for e in recorded_events)
