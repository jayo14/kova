import uuid
from unittest.mock import AsyncMock, patch
import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.auth.dependencies import _get_jwt_secret
from app.modules.auth.token_service import create_api_token
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.api.routes.viewport import (
    _authenticate_ws_token,
    _verify_execution_access,
    viewport_stream,
)


def _make_token(sub: str, exp: int = 9999999999, secret: str | None = None) -> str:
    payload = {
        "sub": sub,
        "aud": settings.OIDC_AUDIENCE or "authenticated",
        "exp": exp,
        "iss": settings.effective_jwt_issuer or "kova",
    }
    return jwt.encode(payload, secret or _get_jwt_secret(), algorithm="HS256")


class DummyWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed_code = None
        self.closed_reason = None
        self.client_state = 1
        self.sent_messages = []

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_code = code
        self.closed_reason = reason

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def receive_text(self):
        from starlette.websockets import WebSocketDisconnect
        raise WebSocketDisconnect(code=1000)


@pytest.mark.asyncio
async def test_authenticate_ws_token_valid():
    user_id = str(uuid.uuid4())
    token = _make_token(user_id)
    res = await _authenticate_ws_token(token)
    assert res == user_id


@pytest.mark.asyncio
async def test_authenticate_ws_token_expired():
    user_id = str(uuid.uuid4())
    token = _make_token(user_id, exp=1000000000)
    res = await _authenticate_ws_token(token)
    assert res is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_forged():
    user_id = str(uuid.uuid4())
    token = _make_token(user_id, secret="wrong-secret-that-does-not-match")
    res = await _authenticate_ws_token(token)
    assert res is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_production_no_token(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    res = await _authenticate_ws_token("")
    assert res is None


@pytest.mark.asyncio
async def test_authenticate_ws_token_api_token(db_session: AsyncSession):
    user = User(id=uuid.uuid4(), email="ws-api-user@kova.local")
    db_session.add(user)
    await db_session.commit()

    token_obj, raw_token = await create_api_token(db_session, user.id, name="WS API Token")
    await db_session.commit()

    res = await _authenticate_ws_token(raw_token, db=db_session)
    assert res == str(user.id)


@pytest.mark.asyncio
async def test_verify_execution_access(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner@kova.local")
    other = User(id=uuid.uuid4(), email="other@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, other, project, flow, execution])
    await db_session.commit()

    # Owner has access
    assert await _verify_execution_access(str(execution.id), str(owner.id), db=db_session) is True
    # Other user denied access
    assert await _verify_execution_access(str(execution.id), str(other.id), db=db_session) is False
    # Non-existent execution denied
    assert await _verify_execution_access(str(uuid.uuid4()), str(owner.id), db=db_session) is False


@pytest.mark.asyncio
async def test_viewport_stream_valid_token(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-ws@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, project, flow, execution])
    await db_session.commit()

    ws = DummyWebSocket()
    token = _make_token(str(owner.id))

    with patch("app.api.routes.viewport.get_control_state", new=AsyncMock(return_value="agent")), \
         patch("app.api.routes.viewport._pump_loop", new=AsyncMock()):
        try:
            await viewport_stream(ws, str(execution.id), token=token, db=db_session)
        except Exception:
            pass

    assert ws.accepted is True
    assert ws.closed_code is None


@pytest.mark.asyncio
async def test_viewport_stream_expired_token(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-ws2@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, project, flow, execution])
    await db_session.commit()

    ws = DummyWebSocket()
    expired_token = _make_token(str(owner.id), exp=1000)

    await viewport_stream(ws, str(execution.id), token=expired_token, db=db_session)
    assert ws.accepted is False
    assert ws.closed_code == 4001


@pytest.mark.asyncio
async def test_viewport_stream_forged_token(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-ws3@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, project, flow, execution])
    await db_session.commit()

    ws = DummyWebSocket()
    forged_token = _make_token(str(owner.id), secret="attacker-forged-secret-123456789012")

    await viewport_stream(ws, str(execution.id), token=forged_token, db=db_session)
    assert ws.accepted is False
    assert ws.closed_code == 4001


@pytest.mark.asyncio
async def test_viewport_stream_another_user_token(db_session: AsyncSession):
    owner = User(id=uuid.uuid4(), email="owner-ws4@kova.local")
    other_user = User(id=uuid.uuid4(), email="other-ws4@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, other_user, project, flow, execution])
    await db_session.commit()

    ws = DummyWebSocket()
    other_token = _make_token(str(other_user.id))

    await viewport_stream(ws, str(execution.id), token=other_token, db=db_session)
    assert ws.accepted is False
    assert ws.closed_code == 4003


@pytest.mark.asyncio
async def test_viewport_stream_production_no_token(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    owner = User(id=uuid.uuid4(), email="owner-ws5@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Proj", base_url="https://example.com")
    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Flow", steps=[])
    execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
    db_session.add_all([owner, project, flow, execution])
    await db_session.commit()

    ws = DummyWebSocket()
    await viewport_stream(ws, str(execution.id), token="", db=db_session)
    assert ws.accepted is False
    assert ws.closed_code == 4001
