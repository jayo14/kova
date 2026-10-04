"""Cross-process viewport stream bridge.

Worker (Celery or in-process asyncio) publishes frames and browser state
to Redis. The FastAPI viewport gateway subscribes and forwards to WebSocket
clients. This is the browser data plane — ephemeral, never persisted.

Channels (binary-safe):
  kova:viewport:frame:{execution_id}  — raw JPEG bytes + state tag
  kova:viewport:state:{execution_id}  — JSON state/url/title/control updates

Frame wire format on the Redis channel:
  b"{state}\\x00{jpeg_bytes}"  (state is short ASCII tag)
"""

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

_text_redis: aioredis.Redis | None = None
_bin_redis: aioredis.Redis | None = None
_text_loop: asyncio.AbstractEventLoop | None = None
_bin_loop: asyncio.AbstractEventLoop | None = None

FRAME_PREFIX = b"kova:viewport:frame"
STATE_PREFIX = b"kova:viewport:state"

# Cap frame size to ~512KB — larger screenshots are a bug or attack
MAX_FRAME_BYTES = 512 * 1024


def frame_channel(execution_id: str) -> str:
    return f"kova:viewport:frame:{execution_id}"


def state_channel(execution_id: str) -> str:
    return f"kova:viewport:state:{execution_id}"


async def _recreate_if_loop_changed(
    client: aioredis.Redis | None,
    loop_holder: list,
    current_loop: asyncio.AbstractEventLoop,
) -> aioredis.Redis | None:
    if client is not None and loop_holder[0] is not None and loop_holder[0] is not current_loop:
        try:
            await client.aclose()
        except Exception:
            pass
        loop_holder[0] = None
        return None
    return client


async def _text_client() -> aioredis.Redis:
    global _text_redis, _text_loop
    loop = asyncio.get_running_loop()
    if _text_redis is not None and _text_loop is not None and _text_loop is not loop:
        try:
            await _text_redis.aclose()
        except Exception:
            pass
        _text_redis = None
        _text_loop = None
    if _text_redis is None:
        kwargs: dict[str, Any] = {"decode_responses": True}
        if settings.REDIS_URL.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = "none"
        _text_redis = aioredis.from_url(settings.REDIS_URL, **kwargs)
        _text_loop = loop
    return _text_redis


async def _bin_client() -> aioredis.Redis:
    global _bin_redis, _bin_loop
    loop = asyncio.get_running_loop()
    if _bin_redis is not None and _bin_loop is not None and _bin_loop is not loop:
        try:
            await _bin_redis.aclose()
        except Exception:
            pass
        _bin_redis = None
        _bin_loop = None
    if _bin_redis is None:
        kwargs: dict[str, Any] = {"decode_responses": False}
        if settings.REDIS_URL.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = "none"
        _bin_redis = aioredis.from_url(settings.REDIS_URL, **kwargs)
        _bin_loop = loop
    return _bin_redis


async def publish_frame(execution_id: str, frame_bytes: bytes, state: str = "observing") -> None:
    """Publish a live viewport frame. Ephemeral — not persisted.

    Degrades gracefully without raising or blocking when Redis is unavailable.
    """
    if not frame_bytes or len(frame_bytes) > MAX_FRAME_BYTES:
        return
    try:
        r = await _bin_client()
        tag = (state or "observing").encode("ascii", errors="replace")[:32]
        await asyncio.wait_for(
            r.publish(frame_channel(execution_id), tag + b"\x00" + frame_bytes),
            timeout=0.5,
        )
    except Exception as e:
        logger.debug("Frame publish failed for %s (graceful degradation): %s", execution_id, e)



async def publish_state(
    execution_id: str,
    state: str,
    url: str = "",
    title: str = "",
    control: str | None = None,
    cursor: dict | None = None,
    loading: bool | None = None,
    **extra: Any,
) -> None:
    """Publish a browser/state update. Small, explicit, ephemeral."""
    payload: dict[str, Any] = {"type": "state", "state": state}
    if url:
        payload["url"] = url
    if title:
        payload["title"] = title
    if control:
        payload["control"] = control
    if cursor:
        payload["cursor"] = cursor
    if loading is not None:
        payload["loading"] = loading
    payload.update(extra)
    try:
        r = await _text_client()
        await r.publish(state_channel(execution_id), json.dumps(payload))
    except Exception as e:
        logger.debug("State publish failed for %s: %s", execution_id, e)


async def subscribe_frames(execution_id: str) -> AsyncIterator[tuple[bytes, str]]:
    """Yield (jpeg_bytes, state) frames. Caller owns pubsub lifecycle."""
    r = await _bin_client()
    pubsub = r.pubsub()
    await pubsub.subscribe(frame_channel(execution_id))
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data") or b""
            if not isinstance(data, (bytes, bytearray)):
                continue
            sep = data.find(b"\x00")
            if sep < 0:
                yield bytes(data), "observing"
            else:
                state = data[:sep].decode("ascii", errors="replace") or "observing"
                yield bytes(data[sep + 1:]), state
    finally:
        try:
            await pubsub.unsubscribe(frame_channel(execution_id))
            await pubsub.aclose()
        except Exception:
            pass


async def subscribe_states(execution_id: str) -> AsyncIterator[dict]:
    """Yield parsed state messages. Caller owns pubsub lifecycle."""
    r = await _text_client()
    pubsub = r.pubsub()
    await pubsub.subscribe(state_channel(execution_id))
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    yield parsed
            except (json.JSONDecodeError, TypeError):
                continue
    finally:
        try:
            await pubsub.unsubscribe(state_channel(execution_id))
            await pubsub.aclose()
        except Exception:
            pass


async def cleanup_stream(execution_id: str) -> None:
    """No persistent keys — channels vanish with subscribers. Hook for symmetry."""
    return None
