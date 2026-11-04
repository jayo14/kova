"""Worker liveness and queue state inspection based strictly on measured signals.

Tracks live Celery workers via heartbeat keys (worker:alive:<hostname>) in Redis,
and queries actual queue backlogs via Redis LLEN so the API can honestly report:
- "No worker is running (queue backlog: N)"
- "Queued - position N"
"""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any
import redis.asyncio as aioredis

from app.config.settings import settings
from app.core.redis_tls import redispy_ssl_kwargs
from app.workers.celery_app import get_queue_for_plan

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


def _get_redis_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "decode_responses": True,
        "socket_connect_timeout": 10.0,
        "socket_timeout": 10.0,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "retry_on_timeout": True,
    }
    if "rediss://" in str(settings.REDIS_URL):
        kwargs.update(redispy_ssl_kwargs())
    return kwargs


async def get_liveness_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, **_get_redis_kwargs())
    return _redis_client


async def get_live_workers() -> list[dict[str, Any]]:
    """Query live worker heartbeat keys from Redis."""
    global _redis_client
    try:
        r = await get_liveness_redis()
        pattern = f"{settings.REDIS_KEY_PREFIX}worker:alive:*"
        keys = await r.keys(pattern)
        if not keys:
            return []
        workers = []
        for key in keys:
            val = await r.get(key)
            if val:
                try:
                    data = json.loads(val)
                    workers.append(data)
                except Exception:
                    workers.append({"key": key})
        return workers
    except Exception as exc:
        logger.debug("Error checking live workers in Redis: %s", exc)
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except Exception:
                pass
            _redis_client = None
        return []


async def get_queue_backlog(plan: str | None = None) -> tuple[int, int]:
    """Measure actual backlog across all queues and position in the requested plan queue.

    Returns:
        (total_backlog, plan_queue_depth)
    """
    global _redis_client
    prefix = settings.CELERY_QUEUE_PREFIX
    all_queues = [
        f"{prefix}kova-free",
        f"{prefix}kova-pro",
        f"{prefix}kova-enterprise",
    ]
    target_queue = get_queue_for_plan(plan)
    total_backlog = 0
    target_depth = 0

    try:
        r = await get_liveness_redis()
        for q in all_queues:
            depth = await r.llen(q)
            total_backlog += depth
            if q == target_queue:
                target_depth = depth
    except Exception as exc:
        logger.debug("Error checking queue lengths in Redis: %s", exc)
        if _redis_client is not None:
            try:
                await _redis_client.aclose()
            except Exception:
                pass
            _redis_client = None

    return total_backlog, target_depth


async def get_queued_status_payload(plan: str | None = None) -> dict[str, Any]:
    """Derive queue status and human-readable message strictly from measured signals."""
    live_workers = await get_live_workers()
    total_backlog, target_depth = await get_queue_backlog(plan)

    if not live_workers:
        return {
            "worker_alive": False,
            "worker_count": 0,
            "queue_backlog": total_backlog,
            "queue_position": None,
            "message": f"No worker is running (queue backlog: {total_backlog})",
        }

    # Position is 1-based index (target depth or at least 1)
    position = max(1, target_depth)
    return {
        "worker_alive": True,
        "worker_count": len(live_workers),
        "queue_backlog": total_backlog,
        "queue_position": position,
        "message": f"Queued - position {position}",
    }
