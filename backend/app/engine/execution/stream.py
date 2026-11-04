"""Cross-process viewport stream bridge.

Worker (Celery or in-process asyncio) publishes frames and browser state
to Redis. The FastAPI viewport gateway subscribes and forwards to WebSocket
clients. This is the browser data plane — ephemeral, never persisted.

Channels (binary-safe):
  {prefix}kova:viewport:frame:{execution_id}  — raw JPEG bytes + state tag
  {prefix}kova:viewport:state:{execution_id}  — JSON state/url/title/control updates

Frame wire format on the Redis channel:
  b"{state}|{masking}\x00{jpeg_bytes}"  (two short ASCII tags; masking is
  "masked", "off", or "unknown" — legacy publishers without a masking tag
  decode as "unknown")
"""

import asyncio
import json
import logging
import ssl
import time
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from app.config.settings import settings
from app.core.redis_tls import redispy_ssl_kwargs

logger = logging.getLogger(__name__)

_text_redis: aioredis.Redis | None = None
_bin_redis: aioredis.Redis | None = None
_text_loop: asyncio.AbstractEventLoop | None = None
_bin_loop: asyncio.AbstractEventLoop | None = None

_memory_frame_subscribers: dict[str, set[asyncio.Queue[tuple[bytes, str, str]]]] = {}
_memory_state_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

# Cap frame size to ~512KB — larger screenshots are a bug or attack
MAX_FRAME_BYTES = 512 * 1024

_SENSITIVE_QUERY_KEYS = {
    "token",
    "secret",
    "code",
    "key",
    "api_key",
    "auth",
    "password",
    "access_token",
    "refresh_token",
    "id_token",
}


def _get_redis_ssl_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if "rediss://" in str(settings.REDIS_URL):
        kwargs.update(redispy_ssl_kwargs())
    return kwargs


def sanitize_url(raw_url: str) -> str:
    """Mask sensitive query parameters (token, secret, code, key, auth, password)."""
    if not raw_url:
        return ""
    try:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
        parsed = urlparse(raw_url)
        if not parsed.query:
            return raw_url
        sanitized_params = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            k_lower = k.lower()
            if k_lower in _SENSITIVE_QUERY_KEYS or any(s in k_lower for s in ("token", "secret", "password")):
                sanitized_params.append((k, "[hidden]"))
            else:
                sanitized_params.append((k, v))
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(sanitized_params), parsed.fragment)
        )
    except Exception:
        return raw_url


def frame_channel(execution_id: str) -> str:
    prefix = getattr(settings, "REDIS_KEY_PREFIX", "")
    return f"{prefix}kova:viewport:frame:{execution_id}"


def state_channel(execution_id: str) -> str:
    prefix = getattr(settings, "REDIS_KEY_PREFIX", "")
    return f"{prefix}kova:viewport:state:{execution_id}"


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
        kwargs: dict[str, Any] = {
            "decode_responses": True,
            "socket_connect_timeout": 3.0,
            "socket_timeout": 3.0,
        }
        kwargs.update(_get_redis_ssl_kwargs())
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
        kwargs: dict[str, Any] = {
            "decode_responses": False,
            "socket_connect_timeout": 3.0,
            "socket_timeout": 3.0,
        }
        kwargs.update(_get_redis_ssl_kwargs())
        _bin_redis = aioredis.from_url(settings.REDIS_URL, **kwargs)
        _bin_loop = loop
    return _bin_redis


def _create_pubsub_client(decode_responses: bool = False) -> aioredis.Redis:
    """Create a dedicated Redis client specifically for pub/sub streams.

    Requirements:
    - socket_timeout=None: long-lived subscriptions must never time out on idle
    - health_check_interval=30: proactive keepalive detection
    - socket_keepalive=True: OS-level TCP keepalive
    """
    kwargs: dict[str, Any] = {
        "decode_responses": decode_responses,
        "socket_connect_timeout": 5.0,
        "socket_timeout": None,
        "health_check_interval": 30,
        "socket_keepalive": True,
    }
    kwargs.update(_get_redis_ssl_kwargs())
    return aioredis.from_url(settings.REDIS_URL, **kwargs)


def encode_frame_tag(state: str, masking: str) -> bytes:
    """Wire-format tag for a frame: '{state}|{masking}'."""
    state_tag = (state or "observing").encode("ascii", errors="replace")[:32]
    masking_tag = (masking or "unknown").encode("ascii", errors="replace")[:16]
    return state_tag + b"|" + masking_tag


def decode_frame_tag(tag: bytes) -> tuple[str, str]:
    """Decode a frame tag; legacy tags (no '|') decode with masking='unknown'."""
    if b"|" in tag:
        state_raw, masking_raw = tag.split(b"|", 1)
        state = state_raw.decode("ascii", errors="replace") or "observing"
        masking = masking_raw.decode("ascii", errors="replace") or "unknown"
    else:
        state = tag.decode("ascii", errors="replace") or "observing"
        masking = "unknown"
    return state, masking


async def publish_frame(
    execution_id: str,
    frame_bytes: bytes,
    state: str = "observing",
    masking: str = "unknown",
) -> None:
    """Publish a live viewport frame. Ephemeral — not persisted."""
    if not frame_bytes or len(frame_bytes) > MAX_FRAME_BYTES:
        return

    # Fan out immediately to local in-memory subscribers (bounded queue, drop oldest on backpressure)
    queues = list(_memory_frame_subscribers.get(execution_id, set()))
    for q in queues:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            q.put_nowait((frame_bytes, state or "observing", masking or "unknown"))
        except asyncio.QueueFull:
            pass

    try:
        r = await _bin_client()
        tag = encode_frame_tag(state, masking)
        await asyncio.wait_for(
            r.publish(frame_channel(execution_id), tag + b"\x00" + frame_bytes),
            timeout=2.5,
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
        payload["url"] = sanitize_url(url)
    if title:
        payload["title"] = title
    if control:
        payload["control"] = control
    if cursor:
        payload["cursor"] = cursor
    if loading is not None:
        payload["loading"] = loading
    payload.update(extra)

    # Fan out immediately to local in-memory subscribers (bounded queue, drop oldest on backpressure)
    s_queues = list(_memory_state_subscribers.get(execution_id, set()))
    for sq in s_queues:
        if sq.full():
            try:
                sq.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            sq.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    try:
        r = await _text_client()
        await r.publish(state_channel(execution_id), json.dumps(payload))
    except Exception as e:
        logger.debug("State publish failed for %s: %s", execution_id, e)


async def subscribe_frames(execution_id: str) -> AsyncIterator[tuple[bytes, str, str]]:
    """Yield (jpeg_bytes, state, masking) frames with auto-reconnecting pubsub."""
    channel = frame_channel(execution_id)
    backoff = 0.5
    max_backoff = 5.0

    while True:
        client = None
        pubsub = None
        try:
            client = _create_pubsub_client(decode_responses=False)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            backoff = 0.5

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data") or b""
                if not isinstance(data, (bytes, bytearray)):
                    continue
                sep = data.find(b"\x00")
                if sep < 0:
                    yield bytes(data), "observing", "unknown"
                else:
                    state, masking = decode_frame_tag(data[:sep])
                    yield bytes(data[sep + 1:]), state, masking
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Frame pubsub connection dropped (%s), reconnecting in %.1fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, max_backoff)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass
            if client:
                try:
                    await client.aclose()
                except Exception:
                    pass


async def subscribe_states(execution_id: str) -> AsyncIterator[dict]:
    """Yield parsed state messages with auto-reconnecting pubsub."""
    channel = state_channel(execution_id)
    backoff = 0.5
    max_backoff = 5.0

    while True:
        client = None
        pubsub = None
        try:
            client = _create_pubsub_client(decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            backoff = 0.5

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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("State pubsub connection dropped (%s), reconnecting in %.1fs", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, max_backoff)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass
            if client:
                try:
                    await client.aclose()
                except Exception:
                    pass


async def cleanup_stream(execution_id: str) -> None:
    """Clear memory queues and associated stream resources."""
    _memory_frame_subscribers.pop(execution_id, None)
    _memory_state_subscribers.pop(execution_id, None)
