"""Integration tests for state-aware flow execution and dynamic prerequisite resolution."""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import uvicorn

from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState
from app.modules.executions.event_types import EventTypes
from app.modules.flows.schemas import FlowStateContract, StateAssertion
from tests.test_app import app as test_app


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    port = _get_free_port()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def test_server():
    async with _run_test_server() as url:
        yield url


@pytest.mark.asyncio
async def test_target_flow_executes_prerequisite_first_and_records_transitions(test_server):
    """Target flow requiring prerequisite runs prerequisite first, transitions through PLANNING -> RESOLVING_PREREQUISITES -> RUNNING -> COMPLETED."""
    runner = FlowRunner()
    execution_id = uuid.uuid4()
    events = []

    async def recorder(eid, etype, payload):
        events.append({"type": etype, "payload": payload})

    # Prerequisite flow produces "student.enrolled:CS101"
    prereq_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Enroll Student",
        persona="student",
        steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
        ],
        state_contract=FlowStateContract(
            persona="student",
            produces=[
                StateAssertion(key="student.enrolled:CS101", value=True),
            ],
        ),
    )

    # Target flow requires "student.enrolled:CS101" and produces "assignment.submitted:CS101"
    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Submit Homework",
        persona="student",
        steps=[
            {"type": "navigate", "value": f"{test_server}/search"},
        ],
        state_contract=FlowStateContract(
            persona="student",
            requires=[StateAssertion(key="student.enrolled:CS101", value=True)],
            produces=[StateAssertion(key="assignment.submitted:CS101", value=True)],
        ),
        success_condition={"url_matches": ".*search.*"},
    )

    result = await runner.run(
        execution_id=execution_id,
        target_flow=target_flow,
        flows=[prereq_flow, target_flow],
        persona="student",
        target_url=test_server,
        event_recorder=recorder,
    )

    assert result["success"] is True, f"Execution failed: {result}"
    event_types = [e["type"] for e in events]
    assert EventTypes.EXECUTION_PLANNED in event_types
    assert EventTypes.PREREQUISITE_RESOLVED in event_types
    assert EventTypes.EXECUTION_STARTED in event_types
    assert EventTypes.EXECUTION_COMPLETED in event_types

    # Final application state contains outputs from both prerequisite and target
    final_state = result["current_state"]
    assert final_state.get("student.enrolled:CS101") is True
    assert final_state.get("assignment.submitted:CS101") is True


@pytest.mark.asyncio
async def test_unsatisfiable_prerequisite_fails_closed_without_browser_actions():
    """Unsatisfiable prerequisite immediately stops execution, emits PREREQUISITE_FAILED, and returns UNVERIFIED."""
    runner = FlowRunner()
    execution_id = uuid.uuid4()
    events = []

    async def recorder(eid, etype, payload):
        events.append({"type": etype, "payload": payload})

    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Admin Operations",
        persona="admin",
        steps=[
            {"type": "navigate", "value": "https://example.com/admin"},
        ],
        state_contract=FlowStateContract(
            persona="admin",
            requires=[StateAssertion(key="role:superadmin", value=True)],
        ),
        success_condition={"url_matches": ".*admin.*"},
    )

    # Browser should NEVER be started for unsatisfiable prerequisite
    with patch("app.engine.execution.runner.BrowserSession") as mock_browser_cls:
        result = await runner.run(
            execution_id=execution_id,
            target_flow=target_flow,
            flows=[target_flow],
            event_recorder=recorder,
        )

        assert mock_browser_cls.call_count == 0

    assert result["success"] is False
    assert result["error_code"] == "PREREQUISITE_FAILED"
    assert result["state"] == "UNVERIFIED"
    assert "role:superadmin" in result["unresolved"]

    event_types = [e["type"] for e in events]
    assert EventTypes.EXECUTION_PLANNED in event_types
    assert EventTypes.PREREQUISITE_FAILED in event_types
    assert EventTypes.BROWSER_STARTED not in event_types


@pytest.mark.asyncio
async def test_contamination_detected_triggers_reset_strategy(test_server):
    """When current state conflicts with target flow preconditions/mutations, contamination is detected and reset invoked."""
    runner = FlowRunner()
    execution_id = uuid.uuid4()
    events = []

    async def recorder(eid, etype, payload):
        events.append({"type": etype, "payload": payload})

    setup_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Prepare Draft",
        persona="student",
        steps=[
            {"type": "navigate", "value": f"{test_server}/search"},
        ],
        state_contract=FlowStateContract(
            persona="student",
            produces=[StateAssertion(key="assignment.status", value="draft")],
        ),
    )

    target_flow = SimpleNamespace(
        id=uuid.uuid4(),
        name="Submit Draft",
        persona="student",
        steps=[
            {"type": "navigate", "value": f"{test_server}/search"},
        ],
        state_contract=FlowStateContract(
            persona="student",
            requires=[StateAssertion(key="assignment.status", value="draft")],
            mutates=["assignment.status"],
            reset_strategy="re_establish",
        ),
        success_condition={"url_matches": ".*search.*"},
    )

    result = await runner.run(
        execution_id=execution_id,
        target_flow=target_flow,
        flows=[setup_flow, target_flow],
        current_state={"assignment.status": "submitted"},  # Contaminated!
        event_recorder=recorder,
    )

    event_types = [e["type"] for e in events]
    assert EventTypes.STATE_CONTAMINATED in event_types
    assert EventTypes.STATE_RESET in event_types
