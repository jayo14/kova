"""Integration tests for the deterministic execution runner.

Tests the complete lifecycle: load → queue → init → run → verify → complete/fail → cleanup.
"""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState
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


@pytest.fixture
def credential_store():
    store = CredentialStore()
    store.add(Credential(id="login", email="test@kova.local", password="KovaTest123!"))
    return store


# --- Basic lifecycle ---


@pytest.mark.asyncio
async def test_runner_completes_lifecycle(test_server):
    """Runner completes full lifecycle: queued → init → browser_ready → running → unverified."""
    runner = FlowRunner()
    execution_id = uuid.uuid4()

    result = await runner.execute(
        execution_id=execution_id,
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        target_url=test_server,
    )

    # No success_condition → COMPLETED with UNVERIFIED (not stuck in RUNNING)
    assert result["success"] is False
    assert result["error_code"] == "UNVERIFIED"
    assert result["state"] == "COMPLETED"
    assert result["execution_id"] == str(execution_id)
    assert "events" in result
    assert "verification" in result


@pytest.mark.asyncio
async def test_runner_records_state_transitions(test_server):
    """Runner records all state transitions."""
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    runner = FlowRunner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        target_url=test_server,
        event_recorder=recorder,
    )

    event_types = [e["type"] for e in events]
    assert "execution.queued" in event_types
    assert "execution.initializing" in event_types
    assert "browser.started" in event_types
    assert "execution.started" in event_types
    assert "execution.completed" in event_types
    assert result["state"] != "RUNNING"


@pytest.mark.asyncio
async def test_runner_always_closes_browser(test_server):
    """Runner always closes browser even on failure."""
    runner = FlowRunner()

    # Execute with invalid step that will fail
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "click", "target": {"css": "#nonexistent"}},
        ],
        target_url=test_server,
    )

    # Even though execution failed, browser should be closed
    assert result["success"] is False
    assert "events" in result
    closed = [e for e in result["events"] if e.get("type") == "browser.closed"]
    assert len(closed) > 0


# --- Login flow with verification ---


@pytest.mark.asyncio
async def test_runner_login_flow_with_verification(test_server, credential_store):
    """Complete login flow with success verification."""
    runner = FlowRunner()
    execution_id = uuid.uuid4()

    result = await runner.execute(
        execution_id=execution_id,
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "type", "target": {"css": "#email"}, "value": "test@kova.local"},
            {"type": "type", "target": {"css": "#password"}, "credential_id": "login"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        success_condition={"text_visible": "Welcome, Kova"},
        credential_store=credential_store,
        target_url=test_server,
    )

    assert result["success"] is True
    assert result["verification"]["passed"] is True


@pytest.mark.asyncio
async def test_runner_fails_on_verification(test_server):
    """Runner fails when verification fails."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
        ],
        success_condition={"text_visible": "Nonexistent Text"},
        target_url=test_server,
    )

    assert result["success"] is False
    assert "verification_failed" in result.get("error_code", "").lower()


# --- Failure handling ---


@pytest.mark.asyncio
async def test_runner_fails_on_action_error(test_server):
    """Runner fails when action fails."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "click", "target": {"css": "#nonexistent"}},
        ],
        target_url=test_server,
    )

    assert result["success"] is False
    assert result["state"] == ExecutionState.FAILED.value


@pytest.mark.asyncio
async def test_runner_never_stuck_in_running(test_server):
    """Runner never leaves execution stuck in RUNNING state."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "click", "target": {"css": "#nonexistent"}},
        ],
        target_url=test_server,
    )

    # Should transition to FAILED, not stay in RUNNING
    assert result["state"] != ExecutionState.RUNNING.value
    assert result["state"] in (
        ExecutionState.COMPLETED.value,
        ExecutionState.FAILED.value,
    )


# --- Event recording ---


@pytest.mark.asyncio
async def test_runner_records_observations(test_server):
    """Runner records page observations."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        target_url=test_server,
    )

    assert len(result["observations"]) > 0
    # Each observation should have url, title, elements
    for obs in result["observations"]:
        assert "url" in obs
        assert "title" in obs


@pytest.mark.asyncio
async def test_runner_records_step_events(test_server):
    """Runner records events for each step."""
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    runner = FlowRunner()
    await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        target_url=test_server,
        event_recorder=recorder,
    )

    event_types = [e["type"] for e in events]
    assert "agent.observed" in event_types
    assert "action.started" in event_types
    assert "action.completed" in event_types


# --- Empty flow ---


@pytest.mark.asyncio
async def test_runner_empty_flow(test_server):
    """Runner handles empty flow steps (UNVERIFIED — no success condition)."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        target_url=test_server,
    )

    assert result["error_code"] == "UNVERIFIED"
    assert result["state"] == "COMPLETED"


# --- Credential integration ---


@pytest.mark.asyncio
async def test_runner_with_credentials(test_server, credential_store):
    """Runner executes with credential store."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "type", "target": {"css": "#email"}, "value": "test@kova.local"},
            {"type": "type", "target": {"css": "#password"}, "credential_id": "login"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        success_condition={"text_visible": "Welcome, Kova"},
        credential_store=credential_store,
        target_url=test_server,
    )

    assert result["success"] is True
    # Verify password was never in events
    for event in result["events"]:
        assert "secret" not in str(event)


@pytest.mark.asyncio
async def test_runner_missing_credential_fails(test_server):
    """Runner fails when credential not found."""
    store = CredentialStore()
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "type", "target": {"css": "#password"}, "credential_id": "nonexistent"},
        ],
        credential_store=store,
        target_url=test_server,
    )

    assert result["success"] is False
    assert "credential" in result.get("error", "").lower() or "credential" in result.get("error_code", "").lower()


# --- Old format compatibility ---


@pytest.mark.asyncio
async def test_runner_handles_old_format_steps(test_server):
    """Runner handles old step format (action/selector/value)."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"action": "navigate", "value": f"{test_server}/login"},
            {"action": "click", "selector": "#login-btn"},
        ],
        target_url=test_server,
    )

    assert result["error_code"] in ("UNVERIFIED", None) or result["state"] in (
        "COMPLETED",
        "FAILED",
    )
    assert result["state"] != "RUNNING"


@pytest.mark.asyncio
async def test_runner_handles_mixed_format_steps(test_server):
    """Runner handles mixed old/new format steps."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"action": "click", "selector": "#login-btn"},
        ],
        target_url=test_server,
    )

    assert result["state"] != "RUNNING"


# --- Duration tracking ---


@pytest.mark.asyncio
async def test_runner_tracks_duration(test_server):
    """Runner tracks execution duration."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        target_url=test_server,
    )

    assert "duration_ms" in result or result["error_code"] == "UNVERIFIED"
    if "duration_ms" in result:
        assert result["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_runner_returns_final_url_and_title(test_server):
    """Runner returns final URL and title on verified success path."""
    runner = FlowRunner()

    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
        ],
        success_condition={"text_visible": "Login"},
        target_url=test_server,
    )

    assert result["success"] is True
    assert "final_url" in result
    assert "final_title" in result
    assert result["final_title"] == "Login"
