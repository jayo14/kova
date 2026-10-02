import pytest

from app.engine.execution.state import ExecutionState
from app.engine.execution.context import ExecutionContext


def test_execution_state_values():
    assert ExecutionState.IDLE == "IDLE"
    assert ExecutionState.QUEUED == "QUEUED"
    assert ExecutionState.INITIALIZING == "INITIALIZING"
    assert ExecutionState.BROWSER_READY == "BROWSER_READY"
    assert ExecutionState.RUNNING == "RUNNING"
    assert ExecutionState.OBSERVING == "OBSERVING"
    assert ExecutionState.ACTING == "ACTING"
    assert ExecutionState.VERIFYING == "VERIFYING"
    assert ExecutionState.COMPLETED == "COMPLETED"
    assert ExecutionState.FAILED == "FAILED"


def test_execution_context_record_event():
    ctx = ExecutionContext(
        execution_id="test-123",
        target_url="http://localhost",
    )
    ctx.record_event("navigate", {"url": "http://localhost"})
    assert len(ctx.events) == 1
    assert ctx.events[0]["type"] == "navigate"
    assert ctx.events[0]["data"]["url"] == "http://localhost"


def test_execution_context_record_observation():
    ctx = ExecutionContext(
        execution_id="test-123",
        target_url="http://localhost",
    )
    ctx.record_observation({"url": "http://localhost", "title": "Test"})
    assert len(ctx.observations) == 1


def test_execution_context_record_error():
    ctx = ExecutionContext(
        execution_id="test-123",
        target_url="http://localhost",
    )
    ctx.record_error("Something went wrong")
    assert len(ctx.errors) == 1
    assert ctx.errors[0] == "Something went wrong"
