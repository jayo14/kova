import json
import logging
import time
from typing import Any

from redis.asyncio import Redis

from app.config.settings import settings
from app.engine.browser.session import BrowserSession, SessionState
from app.modules.flows.auth.authenticator import Authenticator
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages ephemeral authenticated browser session state (cookies, storage).

    Keyed by (execution_id, persona) and persisted to Redis with TTL expiration.
    Falls back gracefully to an in-memory store when Redis is unreachable.
    Never persists cookies to relational database tables.
    """

    def __init__(self, redis_client: Redis | None = None):
        self._redis = redis_client
        self._memory_store: dict[str, tuple[SessionState, float]] = {}

    def _cache_key(self, execution_id: str, persona: str) -> str:
        return f"kova:session:{execution_id}:{persona}"

    async def get(self, execution_id: str, persona: str) -> SessionState | None:
        """Retrieve cached session state if available and not expired."""
        key = self._cache_key(execution_id, persona)

        # 1. Try Redis
        if self._redis:
            try:
                raw_data = await self._redis.get(key)
                if raw_data:
                    data = json.loads(raw_data)
                    return SessionState.from_dict(data)
            except Exception as e:
                logger.debug("Redis error retrieving session %s: %s", key, e)

        # 2. Check in-memory store
        if key in self._memory_store:
            state, expires_at = self._memory_store[key]
            if time.time() < expires_at:
                return state
            else:
                del self._memory_store[key]

        return None

    async def set(
        self,
        execution_id: str,
        persona: str,
        state: SessionState,
        ttl_seconds: int = 1800,
    ) -> None:
        """Store session state with TTL."""
        key = self._cache_key(execution_id, persona)

        # 1. In-memory store
        self._memory_store[key] = (state, time.time() + ttl_seconds)

        # 2. Try Redis
        if self._redis:
            try:
                payload = json.dumps(state.to_dict())
                await self._redis.setex(key, ttl_seconds, payload)
            except Exception as e:
                logger.debug("Redis error setting session %s: %s", key, e)

    async def clear(self, execution_id: str, persona: str | None = None) -> None:
        """Clear session state for an execution."""
        if persona:
            keys_to_clear = [self._cache_key(execution_id, persona)]
        else:
            prefix = f"kova:session:{execution_id}:"
            keys_to_clear = [k for k in self._memory_store if k.startswith(prefix)]

        for k in keys_to_clear:
            self._memory_store.pop(k, None)
            if self._redis:
                try:
                    await self._redis.delete(k)
                except Exception:
                    pass

    async def get_or_establish(
        self,
        execution_id: str,
        persona: str,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        authenticator: Authenticator,
        event_recorder: Any | None = None,
    ) -> tuple[SessionState, bool]:
        """Return existing cached session state or establish one via Authenticator.

        Returns (session_state, was_reused).
        """
        cached = await self.get(execution_id, persona)
        if cached:
            logger.info("Restoring existing session state for execution %s persona %s", execution_id, persona)
            await browser.restore_session_state(cached)
            return cached, True

        logger.info("Establishing new session state for execution %s persona %s via Authenticator", execution_id, persona)
        auth_result = await authenticator.authenticate(
            capability=capability,
            browser=browser,
            credential=credential,
            execution_id=execution_id,
            event_recorder=event_recorder,
        )

        if not auth_result.success or not auth_result.session_state:
            raise RuntimeError(
                f"Authentication failed for persona '{persona}': {auth_result.failure_reason}"
            )

        ttl = getattr(capability, "session_ttl_seconds", 1800)
        await self.set(execution_id, persona, auth_result.session_state, ttl_seconds=ttl)
        return auth_result.session_state, False
