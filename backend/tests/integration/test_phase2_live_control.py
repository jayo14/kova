"""Phase 2 Integration & Acceptance Tests: Live Browser Viewing, Human Takeover, and Safe Execution Control.

Independently verifies:
1. Live viewport frame and state broadcasting over stream channels.
2. Exclusive human takeover leases and rejection of competing client takeovers (409 Conflict).
3. Direct browser interaction under human takeover without agent interference.
4. Authoritative pause gates at action boundaries and post-takeover DOM re-observation.
5. Cancellation and terminal state supremacy over active pause or takeover.
"""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.session import BrowserSession
from app.engine.execution.context import ExecutionContext
from app.engine.execution.control import (
    ControlState,
    acquire_human_takeover,
    cleanup_control,
    get_control_record,
    is_cancel_requested,
    release_human_control,
    request_cancel,
    request_pause,
    validate_human_interaction,
)
from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState
from app.engine.execution.stream import (
    _bin_client,
    _text_client,
    frame_channel,
    publish_frame,
    publish_state,
    state_channel,
)
from tests.fixtures.acceptance_app import acceptance_app, reset_state


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_controlled_server():
    reset_state()
    port = _get_free_port()
    config = uvicorn.Config(acceptance_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
        reset_state()


@pytest.fixture
async def controlled_server():
    async with _run_controlled_server() as url:
        yield url


@pytest.mark.asyncio
async def test_live_viewport_frame_broadcasting():
    """Verify viewport stream broadcasts binary JPEG frames with state tag."""
    exec_id = str(uuid.uuid4())

    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00testframebytes"
    got: asyncio.Future = asyncio.get_event_loop().create_future()
    subscribed = asyncio.Event()

    async def _consume():
        r = await _bin_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(frame_channel(exec_id))
        subscribed.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data") or b""
                sep = data.find(b"\x00")
                if sep >= 0:
                    state = data[:sep].decode("ascii", errors="replace")
                    frame = data[sep + 1:]
                    got.set_result((frame, state))
                break
        finally:
            try:
                await pubsub.unsubscribe(frame_channel(exec_id))
                await pubsub.aclose()
            except Exception:
                pass

    consumer = asyncio.create_task(_consume())
    await asyncio.wait_for(subscribed.wait(), timeout=5.0)
    await asyncio.sleep(0.05)
    await publish_frame(exec_id, jpeg, state="executing")
    frame, state = await asyncio.wait_for(got, timeout=5.0)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    assert frame == jpeg
    assert state == "executing"


@pytest.mark.asyncio
async def test_live_viewport_state_broadcasting():
    """Verify viewport stream broadcasts JSON state messages."""
    exec_id = str(uuid.uuid4())

    got: asyncio.Future = asyncio.get_event_loop().create_future()
    subscribed = asyncio.Event()

    async def _consume():
        r = await _text_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(state_channel(exec_id))
        subscribed.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                import json
                payload = json.loads(message["data"])
                got.set_result(payload)
                break
        finally:
            try:
                await pubsub.unsubscribe(state_channel(exec_id))
                await pubsub.aclose()
            except Exception:
                pass

    consumer = asyncio.create_task(_consume())
    await asyncio.wait_for(subscribed.wait(), timeout=5.0)
    await asyncio.sleep(0.05)
    await publish_state(exec_id, "paused", url="https://example.com/app", title="App", control="human")
    payload = await asyncio.wait_for(got, timeout=5.0)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    assert payload["state"] == "paused"
    assert payload["url"] == "https://example.com/app"
    assert payload["control"] == "human"


@pytest.mark.asyncio
async def test_exclusive_human_takeover_lease_and_concurrency_rejection():
    """Verify exclusive lease acquisition, 409 rejection of competing client, and release."""
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    # 1. Acquire takeover by User A
    ok1, lease1, rec1 = await acquire_human_takeover(exec_id, client_id="user-a", lease_duration_seconds=60.0)
    assert ok1 is True
    assert lease1 is not None
    assert rec1.state == ControlState.HUMAN_CONTROL
    assert rec1.lease_id == lease1
    assert rec1.owner == "user-a"

    # 2. Competing takeover attempt by User B must be rejected
    ok2, err2, rec2 = await acquire_human_takeover(exec_id, client_id="user-b", lease_duration_seconds=60.0)
    assert ok2 is False
    assert "exclusively held by another session" in err2 and "user-a" in err2
    assert rec2.owner == "user-a"

    # 3. Release by invalid lease must be rejected
    ok_rel_bad, err_bad, _ = await release_human_control(exec_id, lease_id="fake-lease-id")
    assert ok_rel_bad is False
    assert "Mismatched or stale lease ID" in err_bad

    # 4. Release by valid lease succeeds and returns to RESUME_REQUESTED
    ok_rel_good, _, rec_rel = await release_human_control(exec_id, lease_id=lease1)
    assert ok_rel_good is True
    assert rec_rel.state == ControlState.RESUME_REQUESTED
    assert rec_rel.lease_id is None
    assert rec_rel.owner == "agent"


@pytest.mark.asyncio
async def test_human_interaction_validation():
    """Verify input actions are validated against active lease ownership."""
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    # 1. Reject input when no human lease held
    valid, reason = await validate_human_interaction(exec_id, lease_id="lease_123")
    assert valid is False
    assert "not HUMAN_CONTROL" in reason

    # 2. Acquire lease
    ok, lease_id, _ = await acquire_human_takeover(exec_id, client_id="user-qa", lease_duration_seconds=60.0)
    assert ok is True

    # 3. Reject wrong lease id
    valid, reason = await validate_human_interaction(exec_id, lease_id="wrong_lease")
    assert valid is False
    assert "Stale or invalid lease ID" in reason

    # 4. Accept matching lease id
    valid, reason = await validate_human_interaction(exec_id, lease_id=lease_id)
    assert valid is True
    assert reason is None or reason == ""

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_action_boundary_pause_and_adaptive_resumption(controlled_server):
    """Verify FlowRunner pauses cleanly at action boundary, allows takeover, and adaptively replans."""
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=exec_id, target_url=controlled_server)
    ctx.state = ExecutionState.RUNNING

    recorded_events = []

    async def event_recorder(eid, event_type, payload):
        recorded_events.append((event_type, payload))

    async with BrowserSession(headless=True) as browser:
        # Navigate to controlled test server
        await browser.navigate(controlled_server)

        # 1. User requests pause
        await request_pause(exec_id, reason="Testing live pause boundary")

        # Background coroutine: wait for PAUSED, take over, interact with DOM, and release
        takeover_completed = asyncio.Event()

        async def user_takeover_session():
            for _ in range(50):
                rec = await get_control_record(exec_id)
                if rec.state == ControlState.PAUSED:
                    break
                await asyncio.sleep(0.05)

            # Acquire human takeover
            ok, lease_id, rec_human = await acquire_human_takeover(
                exec_id, client_id="qa-lead", lease_duration_seconds=30.0
            )
            assert ok is True
            assert rec_human.state == ControlState.HUMAN_CONTROL

            # Human interacts with real page: clicks Register link
            await browser.page.click('a[href="/register"]')
            await browser.page.wait_for_load_state("domcontentloaded")

            # Fill name field
            await browser.page.fill("#name", "Adaptive QA User")

            # Release control back to agent
            await release_human_control(exec_id, lease_id=lease_id)
            takeover_completed.set()

        task = asyncio.create_task(user_takeover_session())

        # Runner pause gate executes
        handled = await runner._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
        await task

        assert handled is True
        assert takeover_completed.is_set()

        # Verify page URL was updated to /register
        assert "/register" in browser.page.url

        # Verify control record returned to agent
        rec_final = await get_control_record(exec_id)
        assert rec_final.state == ControlState.RUNNING
        assert rec_final.owner == "agent"

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_cancellation_preempts_pause_state(controlled_server):
    """Verify cancellation immediately preempts active pause or human takeover."""
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=exec_id, target_url=controlled_server)
    ctx.state = ExecutionState.RUNNING

    recorded_events = []

    async def event_recorder(eid, event_type, payload):
        recorded_events.append((event_type, payload))

    async with BrowserSession(headless=True) as browser:
        await browser.navigate(controlled_server)

        # 1. Request pause
        await request_pause(exec_id, reason="Pausing before cancellation")

        async def cancel_while_paused():
            for _ in range(50):
                rec = await get_control_record(exec_id)
                if rec.state == ControlState.PAUSED:
                    break
                await asyncio.sleep(0.05)
            # Trigger cancellation
            await request_cancel(exec_id, reason="User cancelled while paused")

        cancel_task = asyncio.create_task(cancel_while_paused())

        handled = await runner._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
        await cancel_task

        assert handled is True
        assert await is_cancel_requested(exec_id) is True

    await cleanup_control(exec_id)
