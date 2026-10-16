from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

# In-memory fallback when Redis is absent or during tests
_memory_rate_limits: dict[str, list[float]] = {}
_redis_unavailable_until: float = 0.0


class RateLimiter:
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client

    async def _get_client(self) -> Optional[aioredis.Redis]:
        global _redis_unavailable_until
        if self._redis is not None:
            return self._redis
        if time.time() < _redis_unavailable_until:
            return None
        try:
            kwargs = {}
            if settings.REDIS_URL.startswith("rediss://"):
                kwargs["ssl_cert_reqs"] = "none"
            client = aioredis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
                **kwargs,
            )
            return client
        except Exception as e:
            _redis_unavailable_until = time.time() + 60.0
            logger.debug("RateLimiter: Redis unavailable, using in-memory: %s", e)
            return None

    async def check_user_rate_limit(
        self, user_id: str, limit: int = 60, window_seconds: int = 60
    ) -> tuple[bool, int]:
        """Check per-user interactive API rate limit (default 60 req/min).

        Returns (allowed: bool, retry_after: int).
        """
        global _redis_unavailable_until
        key = f"ratelimit:user:{user_id}"
        client = await self._get_client()

        if client:
            try:
                count = await client.incr(key)
                if count == 1:
                    await client.expire(key, window_seconds)
                if count > limit:
                    ttl = await client.ttl(key)
                    await client.aclose()
                    return False, max(1, ttl)
                await client.aclose()
                return True, 0
            except Exception as e:
                _redis_unavailable_until = time.time() + 60.0
                try:
                    await client.aclose()
                except Exception:
                    pass
                logger.debug("Redis rate limit check failed: %s, falling back to memory", e)

        # In-memory sliding window fallback
        now = time.time()
        cutoff = now - window_seconds
        records = _memory_rate_limits.setdefault(key, [])
        # Prune old timestamps
        records = [ts for ts in records if ts > cutoff]
        _memory_rate_limits[key] = records

        if len(records) >= limit:
            oldest = records[0]
            retry_after = max(1, int(oldest + window_seconds - now))
            return False, retry_after

        records.append(now)
        return True, 0

    async def check_org_execution_limit(
        self, org_id: str, daily_limit: int, window_seconds: int = 86400
    ) -> tuple[bool, int]:
        """Check per-org daily execution limit against OrganizationQuota.

        Returns (allowed: bool, retry_after: int).
        """
        global _redis_unavailable_until
        key = f"ratelimit:org_exec:{org_id}"
        client = await self._get_client()

        if client:
            try:
                count = await client.incr(key)
                if count == 1:
                    await client.expire(key, window_seconds)
                if count > daily_limit:
                    ttl = await client.ttl(key)
                    await client.aclose()
                    return False, max(1, ttl)
                await client.aclose()
                return True, 0
            except Exception as e:
                _redis_unavailable_until = time.time() + 60.0
                try:
                    await client.aclose()
                except Exception:
                    pass
                logger.debug("Redis org exec limit check failed: %s, using memory", e)

        now = time.time()
        cutoff = now - window_seconds
        records = _memory_rate_limits.setdefault(key, [])
        records = [ts for ts in records if ts > cutoff]
        _memory_rate_limits[key] = records

        if len(records) >= daily_limit:
            oldest = records[0]
            retry_after = max(1, int(oldest + window_seconds - now))
            return False, retry_after

        records.append(now)
        return True, 0

    @classmethod
    def reset_in_memory(cls):
        _memory_rate_limits.clear()


rate_limiter = RateLimiter()


async def check_rate_limit(
    request: Request,
    response: Response,
) -> None:
    """FastAPI dependency to rate limit interactive requests by user or IP."""
    from app.modules.auth.dependencies import get_optional_current_user

    # Determine identifier (user ID or client IP)
    auth_header = request.headers.get("authorization", "")
    token = request.headers.get("x-api-key") or (auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else "")
    client_id = f"token_{token[:16]}" if token else (request.client.host if request.client else "unknown")

    allowed, retry_after = await rate_limiter.check_user_rate_limit(client_id, limit=60, window_seconds=60)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
