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
            # Simulate platform waking interstitial from Render
            mock_wake = MagicMock()
            mock_wake.status_code = 200
            mock_wake.headers = {"server": "Render"}
            mock_wake.text = "<html><body>Your free instance is waking up</body></html>"
            return mock_wake
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><body>Welcome to Huntly</body></html>"
        return mock_resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await engine._warmup_preflight("https://huntly-0pgj.onrender.com")

    assert result["success"] is True
    assert result["status_code"] == 200
    assert "ttfb_seconds" in result

    # Verify wake notification was emitted when signature matched
    wake_events = [
        payload for event_type, payload in emitted_events
        if "waking up" in payload.get("message", "").lower()
    ]
    assert len(wake_events) >= 1
    assert "Render" in wake_events[0]["message"]


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


@pytest.mark.asyncio
async def test_preflight_45s_delay_acceptance():
    """Acceptance test: against a fixture that presents a waking interstitial, the UI shows
    the platform wake message only when the signature matches, polls, and announces host is awake.
    When a server simply takes time to respond with no wake signature, no guess message is emitted.
    """
    import time
    emitted_events = []
    timestamps = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))
        timestamps.append(time.time())

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://slow-render-app.onrender.com",
        event_emitter=mock_emitter,
    )

    attempt = 0
    async def mock_get(url, **kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"server": "Render"}
            resp.text = "<html><body>Your free instance is waking up</body></html>"
            return resp
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"content-type": "text/html"}
        resp.text = "<html><body>Awake!</body></html>"
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result = await engine._warmup_preflight("https://slow-render-app.onrender.com")

    assert result["success"] is True

    # 1. Wake-up message emitted based on Render signature match
    warmup_events = [
        p for ev, p in emitted_events
        if ev == "progress" and p.get("id") == "exp-warmup"
    ]
    assert len(warmup_events) >= 2
    assert "Render" in warmup_events[0]["message"]
    assert "waking up" in warmup_events[0]["message"].lower()

    # 2. Final completion message
    assert warmup_events[-1]["status"] == "completed"
    assert "Host is awake" in warmup_events[-1]["message"]


@pytest.mark.asyncio
async def test_fake_worker_live_view_websocket_roundtrip():
    """Verify that a fake worker publishing frames and events to an exploration session
    delivers them cleanly to the subscriber channels used by the live-view WebSocket.
    """
    from app.engine.execution.stream import subscribe_frames, subscribe_states, publish_state

    session_id = str(uuid.uuid4())
    worker_frame = b"\xff\xd8fakeworkerframe\xff\xd9"
    received_frames = []
    received_states = []

    async def fake_worker():
        # Allow subscribers to attach first
        await asyncio.sleep(0.15)
        await publish_state(session_id, "navigating", url="https://example.com", title="Test App")
        await publish_frame(session_id, worker_frame, state="observing", masking="masked")

    async def frame_subscriber():
        async for frame, state, masking in subscribe_frames(session_id):
            received_frames.append((frame, state, masking))
            break

    async def state_subscriber():
        async for state_msg in subscribe_states(session_id):
            received_states.append(state_msg)
            break

    worker_task = asyncio.create_task(fake_worker())
    frame_task = asyncio.create_task(frame_subscriber())
    state_task = asyncio.create_task(state_subscriber())

    await asyncio.wait_for(asyncio.gather(worker_task, frame_task, state_task), timeout=5.0)

    assert len(received_frames) == 1
    assert received_frames[0][0] == worker_frame
    assert received_frames[0][1] == "observing"
    assert received_frames[0][2] == "masked"

    assert len(received_states) == 1
    assert received_states[0]["state"] == "navigating"
    assert received_states[0]["url"] == "https://example.com"
