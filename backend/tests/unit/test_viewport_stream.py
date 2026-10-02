"""Tests for Redis viewport stream bridge and control channel."""

import asyncio
import json
import uuid

import pytest

from app.engine.execution.control import (
    check_pause,
    cleanup_control,
    get_control_state,
    get_pending_input,
    queue_user_input,
    set_control_state,
    publish_command,
)
from app.engine.execution.stream import (
    frame_channel,
    state_channel,
    publish_frame,
    publish_state,
    subscribe_frames,
    subscribe_states,
)


@pytest.fixture
def exec_id():
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_control_set_get_pause(exec_id):
    await set_control_state(exec_id, "human")
    assert await get_control_state(exec_id) == "human"
    assert await check_pause(exec_id) is True
    await set_control_state(exec_id, "agent")
    assert await check_pause(exec_id) is False
    await cleanup_control(exec_id)
    assert await get_control_state(exec_id) == "agent"


@pytest.mark.asyncio
async def test_queue_and_drain_input(exec_id):
    await queue_user_input(exec_id, {"kind": "click", "x": 10, "y": 20})
    await queue_user_input(exec_id, {"kind": "type", "text": "hello"})
    pending = await get_pending_input(exec_id)
    assert len(pending) == 2
    assert pending[0]["kind"] == "click"
    assert pending[1]["text"] == "hello"
    # Second drain is empty (at-most-once)
    again = await get_pending_input(exec_id)
    assert again == []
    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_queue_nav_commands(exec_id):
    await queue_user_input(exec_id, {"kind": "nav_back"})
    await queue_user_input(exec_id, {"kind": "nav_forward"})
    await queue_user_input(exec_id, {"kind": "nav_reload"})
    pending = await get_pending_input(exec_id)
    kinds = [m["kind"] for m in pending]
    assert kinds == ["nav_back", "nav_forward", "nav_reload"]
    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_frame_publish_subscribe_roundtrip(exec_id):
    jpeg = b"\xff\xd8fakejpegdata\xff\xd9"
    got: asyncio.Future = asyncio.get_event_loop().create_future()
    subscribed = asyncio.Event()

    async def _consume():
        from app.engine.execution.stream import _bin_client, frame_channel
        r = await _bin_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(frame_channel(exec_id))
        subscribed.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message["data"]
                sep = data.find(b"\x00")
                state = data[:sep].decode("ascii", errors="replace")
                frame = data[sep + 1:]
                if not got.done():
                    got.set_result((frame, state))
                break
        finally:
            try:
                await pubsub.unsubscribe(frame_channel(exec_id))
                await pubsub.aclose()
            except Exception:
                pass

    consumer = asyncio.create_task(_consume())
    await asyncio.wait_for(subscribed.wait(), timeout=3.0)
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
async def test_state_publish_subscribe_roundtrip(exec_id):
    got: asyncio.Future = asyncio.get_event_loop().create_future()
    subscribed = asyncio.Event()

    async def _consume():
        from app.engine.execution.stream import _text_client, state_channel
        r = await _text_client()
        pubsub = r.pubsub()
        await pubsub.subscribe(state_channel(exec_id))
        subscribed.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                payload = json.loads(message["data"])
                if not got.done():
                    got.set_result(payload)
                break
        finally:
            try:
                await pubsub.unsubscribe(state_channel(exec_id))
                await pubsub.aclose()
            except Exception:
                pass

    consumer = asyncio.create_task(_consume())
    await asyncio.wait_for(subscribed.wait(), timeout=3.0)
    await asyncio.sleep(0.05)
    await publish_state(exec_id, "paused", url="https://example.com", title="Ex", control="human")
    payload = await asyncio.wait_for(got, timeout=5.0)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    assert payload["state"] == "paused"
    assert payload["url"] == "https://example.com"
    assert payload["control"] == "human"


@pytest.mark.asyncio
async def test_frame_oversize_rejected(exec_id):
    # publish_frame silently drops frames over MAX_FRAME_BYTES
    from app.engine.execution import stream
    huge = b"x" * (stream.MAX_FRAME_BYTES + 1)
    # Should not raise
    await publish_frame(exec_id, huge, state="executing")
    # Empty frames dropped
    await publish_frame(exec_id, b"", state="executing")


@pytest.mark.asyncio
async def test_publish_command_reaches_channel(exec_id):
    got: asyncio.Future = asyncio.get_event_loop().create_future()
    subscribed = asyncio.Event()

    async def _consume():
        from app.engine.execution.control import subscribe_commands, _get_redis
        r = await _get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(f"kova:control:commands:{exec_id}")
        subscribed.set()
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                import json as _json
                cmd = _json.loads(message["data"])
                if not got.done():
                    got.set_result(cmd)
                break
        finally:
            try:
                await pubsub.unsubscribe(f"kova:control:commands:{exec_id}")
                await pubsub.aclose()
            except Exception:
                pass

    consumer = asyncio.create_task(_consume())
    await asyncio.wait_for(subscribed.wait(), timeout=3.0)
    await asyncio.sleep(0.05)
    await publish_command(exec_id, "pause")
    cmd = await asyncio.wait_for(got, timeout=5.0)
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    assert cmd["command"] == "pause"


def test_channel_names_are_scoped():
    eid = "abc-123"
    assert frame_channel(eid) == f"kova:viewport:frame:{eid}"
    assert state_channel(eid) == f"kova:viewport:state:{eid}"
