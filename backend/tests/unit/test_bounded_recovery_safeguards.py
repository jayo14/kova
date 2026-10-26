import uuid
import pytest
from unittest.mock import AsyncMock, patch
from app.engine.execution.runner import (
    FlowRunner,
    ExecutionError,
    classify_execution_failure,
    ErrorCode,
)
from app.engine.execution.context import ExecutionContext
from app.engine.execution.state import ExecutionState


def test_failure_classification_categories():
    assert classify_execution_failure("net::ERR_NAME_NOT_RESOLVED") == "NAVIGATION_ERROR"
    assert classify_execution_failure("Element is detached from document") == "STALE_ELEMENT"
    assert classify_execution_failure("Element was covered or hidden") == "DOM_MUTATED"
    assert classify_execution_failure("Verification failed: expected '/dash'") == "ASSERTION_FAILED"
    assert classify_execution_failure("Auth barrier: login required") == "AUTH_BARRIER"

    step_delete = {"type": "click", "target": {"text": "Delete Record"}}
    assert classify_execution_failure("Timeout 5000ms exceeded", step=step_delete) == "NON_IDEMPOTENT_SUBMISSION_UNCERTAIN"


@pytest.mark.asyncio
async def test_non_idempotent_action_halts_without_retry():
    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=str(uuid.uuid4()), target_url="https://example.com")
    ctx.state = ExecutionState.RUNNING
    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/records/new"
    mock_browser.observe.return_value = {"text": "Creation form"}

    mock_executor = AsyncMock()
    mock_executor.execute.side_effect = ExecutionError("Network timeout during submission", ErrorCode.ACTION_FAILED)

    step = {
        "step_id": "step-submit",
        "type": "click",
        "target": {"text": "Save Record"},
    }

    recorded_events = []
    def recorder(evt):
        recorded_events.append(evt)

    with pytest.raises(ExecutionError) as exc_info:
        await runner._execute_step_with_retry(
            ctx=ctx,
            browser=mock_browser,
            action_executor=mock_executor,
            step=step,
            step_index=1,
            event_recorder=recorder,
        )

    # Must halt with NON_IDEMPOTENT_SUBMISSION_UNCERTAIN error code
    assert exc_info.value.error_code == "NON_IDEMPOTENT_SUBMISSION_UNCERTAIN"
    # Exactly ONE attempt was made — no blind replay!
    assert mock_executor.execute.call_count == 1
    # Recorded action.idempotency_halted event
    assert any(e.get("type") == "action.idempotency_halted" for e in ctx.events)


@pytest.mark.asyncio
async def test_re_observation_occurs_on_target_not_found():
    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=str(uuid.uuid4()), target_url="https://example.com")
    ctx.state = ExecutionState.RUNNING
    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/form"
    mock_browser.observe.return_value = {"text": "Hydrated form"}

    mock_executor = AsyncMock()
    # First attempt fails with TARGET_NOT_FOUND, second attempt succeeds
    mock_executor.execute.side_effect = [
        ExecutionError("Target not found", ErrorCode.TARGET_NOT_FOUND),
        {"success": True},
    ]

    # Use an idempotent fill step so retry is permitted
    step = {
        "step_id": "step-fill",
        "type": "fill",
        "target": "#username",
        "value": "user@example.com",
    }

    await runner._execute_step_with_retry(
        ctx=ctx,
        browser=mock_browser,
        action_executor=mock_executor,
        step=step,
        step_index=1,
        event_recorder=None,
    )

    # Two attempts were made
    assert mock_executor.execute.call_count == 2
    # Re-observation occurred between attempts
    mock_browser.observe.assert_awaited()
