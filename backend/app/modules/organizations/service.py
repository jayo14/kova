from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.auth.rate_limiter import rate_limiter
from app.modules.organizations.models import Organization, OrganizationQuota
from app.modules.organizations.repository import OrganizationRepository

logger = logging.getLogger(__name__)

# In-memory concurrent executions tracker fallback
_memory_concurrent_counts: dict[str, int] = {}
_redis_unavailable_until: float = 0.0


class OrganizationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = OrganizationRepository(db)

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        global _redis_unavailable_until
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
            logger.debug("Redis connection failed in OrganizationService: %s", e)
            return None

    async def check_execution_quota(self, org_id: uuid.UUID) -> None:
        """Check if an organization can launch a new execution.

        Raises HTTPException(429) if daily or concurrent limits are exceeded.
        """
        quota = await self.repo.get_quota(org_id)
        if not quota:
            return

        # 1. Check daily limit
        allowed, retry_after = await rate_limiter.check_org_execution_limit(
            str(org_id), daily_limit=quota.max_executions_per_day
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Organization daily execution quota ({quota.max_executions_per_day}) exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        # 2. Check concurrent executions limit
        current_active = await self.get_active_concurrent_count(org_id)
        if current_active >= quota.max_concurrent_executions:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Organization concurrent execution quota ({quota.max_concurrent_executions}) reached. Status: org_at_capacity",
                headers={"Retry-After": "30"},
            )

    async def get_active_concurrent_count(self, org_id: uuid.UUID) -> int:
        key = f"org_concurrent:{org_id}"
        client = await self._get_redis()
        if client:
            try:
                val = await client.get(key)
                await client.aclose()
                return int(val) if val else 0
            except Exception:
                pass
        return _memory_concurrent_counts.get(str(org_id), 0)

    async def acquire_execution_slot(
        self, org_id: uuid.UUID, queue_timeout: int = 120, poll_interval: float = 0.5
    ) -> bool:
        """Acquire a concurrent execution slot, waiting up to queue_timeout seconds if at capacity."""
        quota = await self.repo.get_quota(org_id)
        max_concurrent = quota.max_concurrent_executions if quota else 4

        start_time = time.time()
        key = f"org_concurrent:{org_id}"

        while time.time() - start_time < queue_timeout:
            client = await self._get_redis()
            if client:
                try:
                    # Atomically check and increment
                    val = await client.incr(key)
                    if val <= max_concurrent:
                        await client.expire(key, 3600)  # 1 hour safety TTL
                        await client.aclose()
                        return True
                    # Revert increment if at capacity
                    await client.decr(key)
                    await client.aclose()
                except Exception:
                    global _redis_unavailable_until
                    _redis_unavailable_until = time.time() + 60.0
                    try:
                        await client.aclose()
                    except Exception:
                        pass

            # In-memory check
            current = _memory_concurrent_counts.get(str(org_id), 0)
            if current < max_concurrent:
                _memory_concurrent_counts[str(org_id)] = current + 1
                return True

            await asyncio.sleep(poll_interval)

        return False

    async def release_execution_slot(self, org_id: uuid.UUID) -> None:
        """Release a concurrent execution slot."""
        key = f"org_concurrent:{org_id}"
        client = await self._get_redis()
        if client:
            try:
                val = await client.decr(key)
                if val < 0:
                    await client.set(key, 0)
                await client.aclose()
            except Exception:
                global _redis_unavailable_until
                _redis_unavailable_until = time.time() + 60.0
                try:
                    await client.aclose()
                except Exception:
                    pass

        current = _memory_concurrent_counts.get(str(org_id), 0)
        _memory_concurrent_counts[str(org_id)] = max(0, current - 1)
