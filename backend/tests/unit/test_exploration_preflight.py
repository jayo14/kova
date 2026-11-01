"""Unit tests for slow/sleeping site handling: preflight warmup, error classification, and live viewport streaming."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.exploration.explorer import ExplorationEngine
from app.engine.execution.stream import (
    publish_frame,
    _bin_client,
    frame_channel,
    decode_frame_tag,
)
from app.api.routes.viewport import _verify_execution_access
from app.modules.exploration.models import ExplorationSession, ExplorationStatus
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_preflight_wakes_up_sleeping_site():
    """Verify that a sleeping site triggers warmup notifications with elapsed time."""
    emitted_events = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://huntly-0pgj.onrender.com",
        event_emitter=mock_emitter,
    )

    attempt_count = 0

    async def mock_get(url, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            # Simulate initial delay while container spins up
            await asyncio.sleep(2.1)
            raise httpx.ConnectTimeout("Connection timed out while waking up")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Welcome to Huntly</body></html>"
        return mock_resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await engine._warmup_preflight("https://huntly-0pgj.onrender.com")

    assert result["success"] is True
    assert result["status_code"] == 200

    # Verify warmup notification was emitted with elapsed_seconds
    warmup_events = [
        payload for event_type, payload in emitted_events
        if "Waking up the site" in payload.get("message", "")
    ]
    assert len(warmup_events) >= 1
    assert "elapsed_seconds" in warmup_events[0]
    assert warmup_events[0]["elapsed_seconds"] >= 2


@pytest.mark.asyncio
async def test_preflight_timeout_classification():
    """Verify that repeated connect timeouts classify as TIMEOUT."""
    emitted_events = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://unresponsive-site.local",
        event_emitter=mock_emitter,
    )

    # Patch time.time so it advances beyond deadline quickly
    mock_now = 1000.0
    def fake_time():
        nonlocal mock_now
        mock_now += 40.0
        return mock_now

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectTimeout("Connect timeout")), \
         patch("time.time", side_effect=fake_time):
        result = await engine._warmup_preflight("https://unresponsive-site.local")

    assert result["success"] is False
    assert result["error_code"] == "TIMEOUT"


@pytest.mark.asyncio
async def test_preflight_unreachable_classification():
    """Verify that DNS/network errors classify as SITE_UNREACHABLE."""
    emitted_events = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://nonexistent-domain-404xyz.local",
        event_emitter=mock_emitter,
    )

    mock_now = 1000.0
    def fake_time():
        nonlocal mock_now
        mock_now += 40.0
        return mock_now

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")), \
         patch("time.time", side_effect=fake_time):
        result = await engine._warmup_preflight("https://nonexistent-domain-404xyz.local")

    assert result["success"] is False
    assert result["error_code"] == "SITE_UNREACHABLE"


@pytest.mark.asyncio
async def test_preflight_tls_error_classification():
    """Verify that SSL certificate failures classify as TLS_ERROR."""
    emitted_events = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://expired-ssl-cert.local",
        event_emitter=mock_emitter,
    )

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")):
        result = await engine._warmup_preflight("https://expired-ssl-cert.local")

    assert result["success"] is False
    assert result["error_code"] == "TLS_ERROR"


@pytest.mark.asyncio
async def test_preflight_bot_blocked_classification():
    """Verify that Cloudflare/bot challenge screens classify as BOT_BLOCKED."""
    emitted_events = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://protected-site.local",
        event_emitter=mock_emitter,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "<html><title>Just a moment...</title><body>Checking your browser before accessing the website.</body></html>"

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        result = await engine._warmup_preflight("https://protected-site.local")

    assert result["success"] is False
    assert result["error_code"] == "BOT_BLOCKED"


@pytest.mark.asyncio
async def test_viewport_access_exploration_session(db_session: AsyncSession):
    """Verify that _verify_execution_access authorizes exploration sessions for their owners."""
    owner = User(id=uuid.uuid4(), email="exp-owner@kova.local")
    other = User(id=uuid.uuid4(), email="exp-other@kova.local")
    project = Project(id=uuid.uuid4(), user_id=owner.id, name="ExpProj", base_url="https://example.com")
    session = ExplorationSession(
        id=uuid.uuid4(),
        user_id=owner.id,
        project_id=project.id,
        url="https://example.com",
        status=ExplorationStatus.CONNECTING.value,
    )
    db_session.add_all([owner, other, project, session])
    await db_session.commit()

    assert await _verify_execution_access(str(session.id), str(owner.id), db=db_session) is True
    assert await _verify_execution_access(str(session.id), str(other.id), db=db_session) is False
    assert await _verify_execution_access(str(uuid.uuid4()), str(owner.id), db=db_session) is False


@pytest.mark.asyncio
async def test_viewport_stream_exploration_channel():
    """Verify that frames published to an exploration channel are delivered via Redis pubsub."""
    exp_id = str(uuid.uuid4())
    test_jpeg = b"\xff\xd8fakeexplorationscreenshot\xff\xd9"
    got: asyncio.Future = asyncio.get_event_loop().create_future()
    subscribed = asyncio.Event()

    async def _consume():
        r = await _bin_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(frame_channel(exp_id))
        subscribed.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data") or b""
                sep = data.find(b"\x00")
                if sep >= 0:
                    state, masking = decode_frame_tag(data[:sep])
                    frame = data[sep + 1:]
                else:
                    frame, state, masking = data, "observing", "unknown"
                if not got.done():
                    got.set_result((frame, state, masking))
                break
        finally:
            try:
                await pubsub.unsubscribe(frame_channel(exp_id))
                await pubsub.aclose()
            except Exception:
                pass

    consumer = asyncio.create_task(_consume())
    await asyncio.wait_for(subscribed.wait(), timeout=5.0)
    await asyncio.sleep(0.05)
    await publish_frame(exp_id, test_jpeg, state="observing", masking="masked")
    delivered_jpeg, state, masking = await asyncio.wait_for(got, timeout=5.0)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass

    assert delivered_jpeg == test_jpeg
    assert state == "observing"
    assert masking == "masked"
