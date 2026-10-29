import uuid
from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.api.routes.viewport import (
    create_ws_ticket,
    consume_ws_ticket,
    _verify_execution_access,
    viewport_stream,
)


class DummyWebSocket:
    """Minimal WebSocket double.

    ``incoming`` holds client messages delivered in order. Once exhausted,
    ``receive_text`` raises ``WebSocketDisconnect`` to end the server loop.
    """

    def __init__(self, incoming=None):
        self.accepted = False
        self.closed_code = None
        self.closed_reason = None
        self.client_state = 1
        self.sent_messages = []
        self._incoming = list(incoming or [])

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_code = code
        self.closed_reason = reason

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect(code=1000)


def _auth_message(ticket):
    import json
    return json.dumps({"type": "authenticate", "ticket": ticket})


@pytest.mark.asyncio
async def test_create_and_consume_ticket_single_use():
    ticket = create_ws_ticket("user-1", ttl_seconds=30)
    assert ticket is not None
    assert consume_ws_ticket(ticket) == "user-1"
    # Single-use: consumed ticket no longer valid
    assert consume_ws_ticket(ticket) is None


@pytest.mark.asyncio
async def test_consume_ticket_unknown_returns_none():
    assert consume_ws_ticket("does-not-exist") is None
    assert consume_ws_ticket("") is None


@pytest.mark.asyncio
async def test_consume_expired_ticket_returns_none():
    ticket = create_ws_ticket("user-1", ttl_seconds=-1)
    assert consume_ws_ticket(ticket) is None


@pytest.mark.asyncio
async def test_verify_execution_access(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner@kova.local")
    other = User(id=uuid.uuid4(), email="other@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, other, project, flow, execution])
    await db_session.commit()

    assert await _verify_execution_access(str(execution.id), str(owner.id), db=db_session) is True
    assert await _verify_execution_access(str(execution.id), str(other.id), db=db_session) is False
    assert await _verify_execution_access(str(uuid.uuid4()), str(owner.id), db=db_session) is False


class _ControlRecord:
    def __init__(self):
        from app.engine.execution.control import ControlState
        self.state = ControlState.RUNNING
        self.generation = 1
        self.checkpoint = None


async def _run_stream(db_session, execution_id, ws):
    with patch("app.api.routes.viewport.get_control_record",
               new=AsyncMock(return_value=_ControlRecord())), \
         patch("app.api.routes.viewport._pump_loop", new=AsyncMock()):
        try:
            await viewport_stream(ws, str(execution_id), db=db_session)
        except Exception:
            pass
    return ws


async def _open_stream(db_session, execution_id, ticket, user_objs):
    for u in user_objs:
        db_session.add(u)
    await db_session.commit()

    ws = DummyWebSocket(incoming=[_auth_message(ticket)])
    return await _run_stream(db_session, execution_id, ws)


@pytest.mark.asyncio
async def test_viewport_stream_valid_ticket(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-ws@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)

    ticket = create_ws_ticket(str(owner.id), ttl_seconds=30)
    ws = await _open_stream(db_session, execution.id, ticket, [owner, project, flow, execution])

    assert ws.accepted is True
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_viewport_stream_ticket_single_use(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-ticket@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)

    ticket = create_ws_ticket(str(owner.id), ttl_seconds=30)
    ws1 = await _open_stream(db_session, execution.id, ticket, [owner, project, flow, execution])
    assert ws1.accepted is True

    # Same ticket used a second time must fail immediately
    ws2 = DummyWebSocket(incoming=[_auth_message(ticket)])
    await _run_stream(db_session, execution.id, ws2)
    assert ws2.accepted is True
    assert ws2.closed_code == 4001


@pytest.mark.asyncio
async def test_viewport_stream_expired_ticket(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-expired-ticket@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)

    ticket = create_ws_ticket(str(owner.id), ttl_seconds=-1)
    ws = await _open_stream(db_session, execution.id, ticket, [owner, project, flow, execution])

    assert ws.accepted is True
    assert ws.closed_code == 4001


@pytest.mark.asyncio
async def test_viewport_stream_empty_ticket(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-empty@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)

    ws = await _open_stream(db_session, execution.id, "", [owner, project, flow, execution])

    assert ws.accepted is True
    assert ws.closed_code == 4001


@pytest.mark.asyncio
async def test_viewport_stream_another_user_ticket(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-other@kova.local")
    other_user = User(id=uuid.uuid4(), email="other-other@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)

    # Ticket issued to a different user
    ticket = create_ws_ticket(str(other_user.id), ttl_seconds=30)
    ws = await _open_stream(db_session, execution.id, ticket, [owner, other_user, project, flow, execution])

    assert ws.accepted is True
    assert ws.closed_code == 4003
