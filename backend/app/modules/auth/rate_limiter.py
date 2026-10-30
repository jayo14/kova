from __future__ import annotations

import hashlib
import logging
import ssl
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)

# In-memory fallback when Redis is absent or during tests
_memory_rate_limits: dict[str, list[float]] = {}
_redis_unavailable_until: float = 0.0


def token_bucket_key(token: str) -> str:
    """Stable, collision-free bucket id for an auth token.

    Hash the full token: a short prefix such as ``eyJhbGciOiJIUzI1`` is the
    shared JWT header of every HS256 token, so prefix keys would put all
    tokens in one bucket.
    """
    return f"tok_{hashlib.sha256(token.encode()).hexdigest()}"


class RateLimiter:
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self._shared_client: Optional[aioredis.Redis] = None

    async def _get_client(self) -> Optional[aioredis.Redis]:
        global _redis_unavailable_until
        if self._redis is not None:
            return self._redis
        if time.time() < _redis_unavailable_until:
            return None
        if self._shared_client is not None:
            return self._shared_client
        try:
            kwargs = {}
            if settings.REDIS_URL.startswith("rediss://"):
                kwargs["ssl_cert_reqs"] = "none"
                kwargs["ssl_check_hostname"] = False
            self._shared_client = aioredis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
                **kwargs,
            )
            return self._shared_client
        except Exception as e:
            _redis_unavailable_until = time.time() + 15.0
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
                ttl = await client.ttl(key)
                if ttl is None or ttl < 0:
                    await client.expire(key, window_seconds)
                    ttl = window_seconds
                if count > limit:
                    return False, max(1, ttl)
                return True, 0
            except Exception as e:
                _redis_unavailable_until = time.time() + 15.0
                if self._shared_client is not None and self._redis is None:
                    try:
                        await self._shared_client.aclose()
                    except Exception:
                        pass
                    self._shared_client = None
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
                ttl = await client.ttl(key)
                if ttl is None or ttl < 0:
                    await client.expire(key, window_seconds)
                    ttl = window_seconds
                if count > daily_limit:
                    return False, max(1, ttl)
                return True, 0
            except Exception as e:
                _redis_unavailable_until = time.time() + 15.0
                if self._shared_client is not None and self._redis is None:
                    try:
                        await self._shared_client.aclose()
                    except Exception:
                        pass
                    self._shared_client = None
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
    client_id = token_bucket_key(token) if token else (request.client.host if request.client else "unknown")

    allowed, retry_after = await rate_limiter.check_user_rate_limit(client_id, limit=60, window_seconds=60)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
