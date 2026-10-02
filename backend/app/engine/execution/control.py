"""Cross-process control channel for browser takeover.

Uses Redis (db 0) for pub/sub coordination between:
- FastAPI WebSocket handler (publisher)
- Celery worker / FlowRunner (subscriber)

Channel per execution: kova:control:{execution_id}
Message format: {"command": "pause"|"resume"|"input", ...data}
"""

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None

CONTROL_PREFIX = "kova:control"
COMMAND_CHANNEL = f"{CONTROL_PREFIX}:commands"
STATE_KEY_PREFIX = f"{CONTROL_PREFIX}:state"
INPUT_KEY_PREFIX = f"{CONTROL_PREFIX}:input"


async def _get_redis() -> aioredis.Redis:
    """Return a Redis client bound to the *current* event loop.

    Cached clients die across loops (pytest/asyncio.run). Recreate when the
    running loop changes so pubsub futures stay valid.
    """
    global _redis, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis is not None and _redis_loop is not None and _redis_loop is not loop:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
        _redis_loop = None
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _redis_loop = loop
    return _redis


def _state_key(execution_id: str) -> str:
    return f"{STATE_KEY_PREFIX}:{execution_id}"


def _input_key(execution_id: str) -> str:
    return f"{INPUT_KEY_PREFIX}:{execution_id}"


async def set_control_state(execution_id: str, state: str) -> None:
    """Set the control state for an execution (agent/human/paused)."""
    r = await _get_redis()
    await r.set(_state_key(execution_id), state, ex=600)


async def get_control_state(execution_id: str) -> str:
    """Get the current control state. Returns 'agent' if not set."""
    r = await _get_redis()
    state = await r.get(_state_key(execution_id))
    return state or "agent"


async def publish_command(execution_id: str, command: str, **data: Any) -> None:
    """Publish a control command to the runner."""
    r = await _get_redis()
    payload = json.dumps({"command": command, **data})
    await r.publish(f"{COMMAND_CHANNEL}:{execution_id}", payload)


async def subscribe_commands(execution_id: str):
    """Subscribe to control commands for an execution. Yields command dicts."""
    r = await _get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"{COMMAND_CHANNEL}:{execution_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    yield json.loads(message["data"])
                except json.JSONDecodeError:
                    pass
    finally:
        await pubsub.unsubscribe(f"{COMMAND_CHANNEL}:{execution_id}")


CANCELLED_KEY_PREFIX = f"{CONTROL_PREFIX}:cancelled"


def _cancelled_key(execution_id: str) -> str:
    return f"{CANCELLED_KEY_PREFIX}:{execution_id}"


async def request_cancel(execution_id: str) -> None:
    """Request cancellation of a running execution.

    Sets a Redis flag the runner checks at the same step boundaries as pause.
    Survives process boundaries (FastAPI → worker) unlike in-memory flags.
    """
    r = await _get_redis()
    await r.set(_cancelled_key(execution_id), "1", ex=600)


async def is_cancel_requested(execution_id: str) -> bool:
    """Check whether cancellation has been requested for this execution."""
    r = await _get_redis()
    return bool(await r.get(_cancelled_key(execution_id)))


async def check_pause(execution_id: str) -> bool:
    """Check if execution should pause. Returns True if paused."""
    state = await get_control_state(execution_id)
    return state in ("human", "paused")


async def wait_for_resume(execution_id: str, timeout: float = 300.0) -> bool:
    """Block until control state returns to 'agent'. Returns True if resumed."""
    import asyncio

    r = await _get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(f"{COMMAND_CHANNEL}:{execution_id}")

    try:
        # Check current state first
        current = await get_control_state(execution_id)
        if current == "agent":
            return True

        # Wait for resume command
        start = asyncio.get_event_loop().time()
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    cmd = json.loads(message["data"])
                    if cmd.get("command") == "resume":
                        return True
                except json.JSONDecodeError:
                    pass

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                return False
    finally:
        await pubsub.unsubscribe(f"{COMMAND_CHANNEL}:{execution_id}")

    return False


async def queue_user_input(execution_id: str, input_msg: dict) -> None:
    """Queue user input for the runner to process."""
    r = await _get_redis()
    await r.rpush(_input_key(execution_id), json.dumps(input_msg))
    await r.expire(_input_key(execution_id), 600)


async def get_pending_input(execution_id: str) -> list[dict]:
    """Get and clear all pending user input."""
    r = await _get_redis()
    key = _input_key(execution_id)
    items = []
    while True:
        item = await r.lpop(key)
        if item is None:
            break
        try:
            items.append(json.loads(item))
        except json.JSONDecodeError:
            pass
    return items


async def cleanup_control(execution_id: str) -> None:
    """Clean up control state for an execution."""
    r = await _get_redis()
    await r.delete(_state_key(execution_id))
    await r.delete(_input_key(execution_id))
    await r.delete(_cancelled_key(execution_id))
