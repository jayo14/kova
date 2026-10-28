"""Unit tests for REST execution and run control endpoints, leases, and WebSocket control messages."""

import uuid
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException

from app.api.routes.executions import (
    get_execution_control,
    pause_execution_endpoint,
    resume_execution_endpoint,
    takeover_execution_endpoint,
    release_execution_control_endpoint,
    interact_execution_endpoint,
    ExecutionPauseRequest,
    ExecutionTakeoverRequest,
    ExecutionReleaseRequest,
    ExecutionInteractRequest,
)
from app.api.routes.runs import (
    get_run_control,
    pause_run,
    resume_run,
)
from app.api.routes.viewport import (
    viewport_stream,
)
from app.engine.execution.control import (
    ControlState,
    cleanup_control,
    get_control_record,
    get_pending_input,
)
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.users.models import User
from app.modules.validation.models import ValidationRun


@pytest.fixture
def test_user():
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash="pw",
    )
    user.id = uuid.uuid4()
    return user



@pytest.fixture
def test_execution(test_user):
    exec_obj = Execution(
        flow_id=uuid.uuid4(),
        status=ExecutionStatus.RUNNING.value,
    )
    exec_obj.id = uuid.uuid4()
    return exec_obj


@pytest.mark.asyncio
async def test_execution_rest_control_lifecycle(test_user, test_execution):
    exec_id = str(test_execution.id)
    await cleanup_control(exec_id)

    db = AsyncMock()

    with patch("app.api.routes.executions._verify_execution_ownership", return_value=test_execution):
        # 1. Get initial control state
        ctrl = await get_execution_control(exec_id, user=test_user, db=db)
        assert ctrl.state == "RUNNING"
        assert ctrl.owner == "agent"

        # 2. Pause execution
        paused_res = await pause_execution_endpoint(
            exec_id,
            data=ExecutionPauseRequest(reason="Inspection"),
            user=test_user,
            db=db,
        )
        assert paused_res.state == "PAUSE_REQUESTED"

        # 3. Takeover execution
        takeover_res = await takeover_execution_endpoint(
            exec_id,
            data=ExecutionTakeoverRequest(lease_duration_seconds=60),
            user=test_user,
            db=db,
        )
        assert takeover_res.state == "HUMAN_CONTROL"
        assert takeover_res.owner == str(test_user.id)
        assert takeover_res.lease_id is not None
        lease_id = takeover_res.lease_id

        # 4. Competing takeover attempt by another user is rejected with 409
        other_user = User(email="other@example.com", name="Other", password_hash="pw")

        other_user.id = uuid.uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await takeover_execution_endpoint(
                exec_id,
                data=ExecutionTakeoverRequest(lease_duration_seconds=60),
                user=other_user,
                db=db,
            )
        assert exc_info.value.status_code == 409
        assert "exclusively held" in exc_info.value.detail.lower()

        # 5. Human interaction queued during takeover
        interact_res = await interact_execution_endpoint(
            exec_id,
            data=ExecutionInteractRequest(
                type="input",
                kind="click",
                x=150,
                y=250,
                lease_id=lease_id,
                generation=takeover_res.generation,
            ),
            user=test_user,
            db=db,
        )
        assert interact_res["status"] == "queued"

        queued = await get_pending_input(exec_id)
        assert len(queued) == 1
        assert queued[0]["x"] == 150

        # 6. Release human control
        release_res = await release_execution_control_endpoint(
            exec_id,
            data=ExecutionReleaseRequest(lease_id=lease_id),
            user=test_user,
            db=db,
        )
        assert release_res.state == "RESUME_REQUESTED"

        # 7. Resume execution
        resume_res = await resume_execution_endpoint(
            exec_id,
            user=test_user,
            db=db,
        )
        assert resume_res.state in ("RESUME_REQUESTED", "RUNNING")

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_terminal_execution_rejects_pause(test_user):
    terminal_exec = Execution(
        flow_id=uuid.uuid4(),
        status=ExecutionStatus.COMPLETED.value,
    )
    terminal_exec.id = uuid.uuid4()
    exec_id = str(terminal_exec.id)

    db = AsyncMock()
    with patch("app.api.routes.executions._verify_execution_ownership", return_value=terminal_exec):
        with pytest.raises(HTTPException) as exc_info:
            await pause_execution_endpoint(exec_id, user=test_user, db=db)
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_run_level_pause_resume(test_user):
    run_id = str(uuid.uuid4())
    exec_id_1 = str(uuid.uuid4())
    exec_id_2 = str(uuid.uuid4())

    await cleanup_control(exec_id_1)
    await cleanup_control(exec_id_2)

    val_run = ValidationRun(
        project_id=uuid.uuid4(),
        status="RUNNING",
        execution_ids=[exec_id_1, exec_id_2],
    )
    val_run.id = uuid.UUID(run_id)

    ex1 = Execution(flow_id=uuid.uuid4(), status=ExecutionStatus.RUNNING.value)
    ex1.id = uuid.UUID(exec_id_1)
    ex2 = Execution(flow_id=uuid.uuid4(), status=ExecutionStatus.RUNNING.value)
    ex2.id = uuid.UUID(exec_id_2)

    db = AsyncMock()

    class FakeScalarResult:
        def scalar_one_or_none(self):
            return val_run

    db.execute.return_value = FakeScalarResult()

    with patch("app.api.routes.runs._verify_project_access", return_value=None), \
         patch("app.modules.executions.repository.ExecutionRepository.get_by_id", side_effect=[ex1, ex2, ex1, ex2]):

        # 1. Pause run
        pause_resp = await pause_run(run_id=run_id, user=test_user, db=db)
        assert pause_resp.state == "PAUSE_REQUESTED"
        assert exec_id_1 in pause_resp.executions
        assert exec_id_2 in pause_resp.executions

        # 2. Get run control
        ctrl_resp = await get_run_control(run_id=run_id, user=test_user, db=db)
        assert ctrl_resp.state == "PAUSE_REQUESTED"

        # 3. Resume run
        resume_resp = await resume_run(run_id=run_id, user=test_user, db=db)
        assert resume_resp.state == "RESUME_REQUESTED"

    await cleanup_control(exec_id_1)
    await cleanup_control(exec_id_2)


class MockWebSocket:
    def __init__(self, incoming_messages: list[dict]):
        self.accepted = False
        self.closed_code = None
        self.closed_reason = None
        self.client_state = 1
        self.sent_messages = []
        self._incoming = list(incoming_messages)

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_code = code
        self.closed_reason = reason

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def send_text(self, text):
        pass

    async def send_bytes(self, b):
        pass

    async def receive_text(self):
        if not self._incoming:
            from starlette.websockets import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)
        import json
        return json.dumps(self._incoming.pop(0))


@pytest.mark.asyncio
async def test_websocket_takeover_and_return_lifecycle():
    exec_id = f"test-ws-takeover-{uuid.uuid4().hex[:8]}"
    await cleanup_control(exec_id)

    user_id = str(uuid.uuid4())

    ws = MockWebSocket([
        {"type": "takeover"},
        {"type": "input", "kind": "click", "x": 100, "y": 200},
        {"type": "return_control"},
    ])

    with patch("app.api.routes.viewport._authenticate_ws_token", return_value=user_id), \
         patch("app.api.routes.viewport._verify_execution_access", return_value=True), \
         patch("app.api.routes.viewport._pump_loop", return_value=None):

        await viewport_stream(
            websocket=ws,
            execution_id=exec_id,
            token="valid-token",
        )

    # Verify WS was accepted
    assert ws.accepted is True

    # Verify takeover_granted sent with lease_id and control changed to human
    types = [m.get("type") for m in ws.sent_messages]
    assert "takeover_granted" in types
    assert "control_changed" in types

    takeover_msg = next(m for m in ws.sent_messages if m.get("type") == "takeover_granted")
    assert takeover_msg["lease_id"] is not None
    assert takeover_msg["control"] == "human"

    # Verify return_control changed back to agent
    return_msgs = [m for m in ws.sent_messages if m.get("type") == "control_changed" and m.get("control") == "agent"]
    assert len(return_msgs) >= 1

    await cleanup_control(exec_id)
