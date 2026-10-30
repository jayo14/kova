"""Secure session management with encrypted storage and race-safe reuse (§Prompt C).

Guarantees:
1. Sessions are keyed by (project_id, persona, origin) with TTL.
2. Payloads are encrypted with Fernet before persisting to Redis or memory store.
3. Plaintext cookies/tokens never exist in Redis or logs.
4. On retrieval, sessions are restored and verified with verify_authenticated before reuse.
5. Races are prevented using distributed locks (short Redis lock / in-memory lock).
6. Wipe operations clear cached sessions when credentials change or are deleted.
"""

import asyncio
import ssl
from contextlib import asynccontextmanager
import json
import logging
import time
from typing import Any, NamedTuple
from urllib.parse import urlparse

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.config.settings import settings
from app.engine.browser.session import BrowserSession, SessionState
from app.modules.credentials.crypto import decrypt_credential, encrypt_credential
from app.modules.flows.auth.authenticator import Authenticator
from app.modules.flows.auth.verifier import AuthReasonCode, verify_authenticated
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


def extract_origin(url: str | None) -> str:
    """Extract normalized origin (scheme://netloc) from URL for session scoping."""
    if not url or not isinstance(url, str):
        return "default"
    u = url.strip()
    if not u.startswith("http://") and not u.startswith("https://") and "://" not in u:
        if u.startswith("/"):
            return "default"
        u = "http://" + u
    try:
        parsed = urlparse(u)
        scheme = (parsed.scheme or "http").lower()
        netloc = (parsed.netloc or "").lower()
        if netloc:
            # normalize default ports
            if netloc.endswith(":80") and scheme == "http":
                netloc = netloc[:-3]
            elif netloc.endswith(":443") and scheme == "https":
                netloc = netloc[:-4]
            return f"{scheme}://{netloc}"
        return u.rstrip("/").lower()
    except Exception:
        return "default"


class SessionEstablishResult(tuple):
    """Result of get_or_establish, supporting both 2-tuple and 3-tuple unpacking."""

    def __new__(cls, session_state: SessionState, was_reused: bool, reason: str = ""):
        return super().__new__(cls, (session_state, was_reused, reason))

    def __iter__(self):
        try:
            import sys
            import dis
            f = sys._getframe(1)
            for instr in dis.get_instructions(f.f_code):
                if instr.offset >= f.f_lasti:
                    if instr.opname.startswith("UNPACK_SEQUENCE"):
                        if instr.arg == 2:
                            return iter((self[0], self[1]))
                        elif instr.arg == 3:
                            return iter((self[0], self[1], self[2]))
                    break
        except Exception:
            pass
        return super().__iter__()

    @property
    def session_state(self) -> SessionState:
        return self[0]

    @property
    def was_reused(self) -> bool:
        return self[1]

    @property
    def reason(self) -> str:
        return self[2]


class SessionManager:
    """Manages secure, encrypted browser session reuse across executions."""

    def __init__(self, redis_client: Redis | None = None):
        self._redis = redis_client
        self._redis_checked: bool = redis_client is not None
        self._redis_available: bool = redis_client is not None
        self._memory_store: dict[str, tuple[str, float]] = {}  # key -> (encrypted_str, expires_at)
        self._memory_locks: dict[str, asyncio.Lock] = {}

    async def _get_redis(self) -> Redis | None:
        if self._redis_checked and not self._redis_available:
            return None
        if self._redis is not None:
            return self._redis
        try:
            redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
            kwargs: dict[str, Any] = {
                "decode_responses": True,
                "socket_connect_timeout": 0.2,
                "socket_timeout": 0.2,
            }
            if redis_url.startswith("rediss://"):
                kwargs["ssl_cert_reqs"] = "none"
            client = aioredis.from_url(redis_url, **kwargs)
            await asyncio.wait_for(client.ping(), timeout=0.2)
            self._redis = client
            self._redis_checked = True
            self._redis_available = True
            return self._redis
        except Exception as e:
            logger.debug("Redis unavailable for SessionManager; using memory store: %s", e)
            self._redis_checked = True
            self._redis_available = False
            return None

    def _cache_key(self, project_id: str, persona: str, origin: str) -> str:
        norm_origin = extract_origin(origin)
        return f"kova:session:{project_id}:{persona}:{norm_origin}"

    def _lock_key(self, project_id: str, persona: str, origin: str) -> str:
        norm_origin = extract_origin(origin)
        return f"kova:lock:auth:{project_id}:{persona}:{norm_origin}"

    @asynccontextmanager
    async def _lock(self, project_id: str, persona: str, origin: str):
        """Short distributed lock preventing simultaneous logins for the same persona."""
        lock_key = self._lock_key(project_id, persona, origin)
        if lock_key not in self._memory_locks:
            self._memory_locks[lock_key] = asyncio.Lock()
        r = await self._get_redis()
        redis_lock = None
        if r:
            try:
                redis_lock = r.lock(lock_key, timeout=15.0, blocking_timeout=20.0)
                await redis_lock.acquire()
            except Exception as e:
                logger.debug("Redis lock acquire error on %s: %s", lock_key, e)
                redis_lock = None

        async with self._memory_locks[lock_key]:
            try:
                yield
            finally:
                if redis_lock:
                    try:
                        await redis_lock.release()
                    except Exception as e:
                        logger.debug("Redis lock release error on %s: %s", lock_key, e)

    async def get(
        self,
        project_id: str,
        persona: str,
        origin: str = "default",
    ) -> SessionState | None:
        """Retrieve and decrypt cached session state. Returns None if expired or absent."""
        key = self._cache_key(project_id, persona, origin)
        encrypted_data: str | None = None

        # 1. Try Redis
        r = await self._get_redis()
        if r:
            try:
                raw = await r.get(key)
                if raw:
                    encrypted_data = str(raw)
            except Exception as e:
                logger.debug("Redis error retrieving session %s: %s", key, e)

        # 2. Check in-memory store
        if not encrypted_data and key in self._memory_store:
            enc_str, expires_at = self._memory_store[key]
            if time.time() < expires_at:
                encrypted_data = enc_str
            else:
                del self._memory_store[key]

        if not encrypted_data:
            return None

        # 3. Decrypt payload with Fernet key
        try:
            decrypted_json = decrypt_credential(encrypted_data)
            payload = json.loads(decrypted_json)
            state_dict = payload.get("session_state") if isinstance(payload, dict) else payload
            return SessionState.from_dict(state_dict)
        except Exception as dec_err:
            logger.warning("Failed to decrypt cached session for %s: %s", key, dec_err)
            await self.clear(project_id, persona, origin)
            return None

    async def set(
        self,
        project_id: str,
        persona: str,
        origin: str | SessionState,
        state: SessionState | None = None,
        execution_id: str | None = None,
        ttl_seconds: int = 1800,
    ) -> None:
        """Encrypt and store session state with TTL."""
        if state is None and isinstance(origin, SessionState):
            state = origin
            origin = "default"
        assert state is not None, "state must be provided"
        key = self._cache_key(project_id, persona, origin)

        payload = {
            "session_state": state.to_dict(),
            "execution_id": execution_id or "audit_unknown",
            "project_id": str(project_id),
            "persona": persona,
            "origin": extract_origin(origin),
            "stored_at": time.time(),
        }

        # Encrypt with Fernet key before writing to any store
        encrypted_str = encrypt_credential(json.dumps(payload))

        # 1. Store in encrypted memory cache
        self._memory_store[key] = (encrypted_str, time.time() + ttl_seconds)

        # 2. Store in Redis
        r = await self._get_redis()
        if r:
            try:
                await r.setex(key, ttl_seconds, encrypted_str)
            except Exception as e:
                logger.debug("Redis error setting session %s: %s", key, e)

    async def clear(
        self,
        project_id: str,
        persona: str | None = None,
        origin: str | None = None,
    ) -> None:
        """Clear session state for a specific scope."""
        if persona and origin:
            keys_to_clear = [self._cache_key(project_id, persona, origin)]
        elif persona:
            prefix = f"kova:session:{project_id}:{persona}:"
            keys_to_clear = [k for k in self._memory_store if k.startswith(prefix)]
        else:
            prefix = f"kova:session:{project_id}:"
            keys_to_clear = [k for k in self._memory_store if k.startswith(prefix)]

        for k in keys_to_clear:
            self._memory_store.pop(k, None)

        r = await self._get_redis()
        if r and keys_to_clear:
            try:
                await r.delete(*keys_to_clear)
            except Exception as e:
                logger.debug("Redis error clearing session keys: %s", e)

    async def wipe(
        self,
        project_id: str,
        persona: str | None = None,
        origin: str | None = None,
    ) -> int:
        """Wipe session states when credentials change or are deleted."""
        logger.info("Wiping cached sessions for project %s (persona=%s, origin=%s)", project_id, persona, origin)
        norm_origin = extract_origin(origin) if origin else None
        cleared_keys: set[str] = set()

        # Memory store scan
        to_del = []
        for k in list(self._memory_store.keys()):
            parts = k.split(":")
            if len(parts) >= 4 and parts[2] == str(project_id):
                if persona and parts[3] != persona:
                    continue
                if norm_origin:
                    key_origin = ":".join(parts[4:])
                    if key_origin != norm_origin:
                        continue
                to_del.append(k)

        for k in to_del:
            self._memory_store.pop(k, None)
            cleared_keys.add(k)

        # Redis store scan & delete
        r = await self._get_redis()
        if r:
            try:
                if persona and norm_origin:
                    pattern = f"kova:session:{project_id}:{persona}:{norm_origin}"
                elif persona:
                    pattern = f"kova:session:{project_id}:{persona}:*"
                else:
                    pattern = f"kova:session:{project_id}:*"

                cursor = 0
                while True:
                    cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        await r.delete(*keys)
                        for k in keys:
                            cleared_keys.add(k if isinstance(k, str) else k.decode("utf-8", errors="ignore"))
                    if cursor == 0:
                        break
            except Exception as e:
                logger.debug("Redis scan error during session wipe: %s", e)

        return len(cleared_keys)

    async def get_or_establish(
        self,
        execution_id: str,
        persona: str,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        authenticator: Authenticator,
        event_recorder: Any | None = None,
        target_url: str | None = None,
    ) -> SessionEstablishResult:
        """Return existing verified session state or establish one via Authenticator.

        Guarantees:
        - Reuses verified active sessions across executions.
        - Validates restored state via verify_authenticated; re-authenticates once if expired.
        - Synchronizes concurrent logins via short lock.
        - Returns SessionEstablishResult (session_state, was_reused, reason).
        """
        project_id = str(getattr(capability, "project_id", None) or getattr(credential, "project_id", None) or "global")
        origin_url = target_url or getattr(capability, "login_url", None) or getattr(browser.page, "url", None)
        origin = extract_origin(origin_url)

        # 1. Fast path: check for existing cached session state
        cached = await self.get(project_id, persona, origin)
        if cached:
            await browser.restore_session_state(cached)
            # Verify that the restored state is actually accepted by the server
            is_valid, reason = await verify_authenticated(browser, capability, target_url=origin_url)
            if is_valid:
                logger.info("Session reused for project %s persona %s origin %s", project_id, persona, origin)
                return SessionEstablishResult(
                    cached, True, "session reused (verified active on server)"
                )
            else:
                logger.info("Cached session for persona %s expired on server (%s); clearing", persona, reason)
                await self.clear(project_id, persona, origin)

        # 2. Synchronized path: acquire lock to prevent login races
        async with self._lock(project_id, persona, origin):
            # Double-checked locking: check if concurrent execution already logged in
            cached_concurrent = await self.get(project_id, persona, origin)
            if cached_concurrent:
                await browser.restore_session_state(cached_concurrent)
                is_valid, _ = await verify_authenticated(browser, capability, target_url=origin_url)
                if is_valid:
                    logger.info("Session reused from concurrent execution for %s:%s", project_id, persona)
                    return SessionEstablishResult(
                        cached_concurrent, True, "session reused (established by concurrent execution)"
                    )

            logger.info("Logging in fresh for project %s persona %s origin %s (execution %s)", project_id, persona, origin, execution_id)
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
            await self.set(
                project_id=project_id,
                persona=persona,
                origin=origin,
                state=auth_result.session_state,
                execution_id=execution_id,
                ttl_seconds=ttl,
            )

            reason_str = "logged in fresh (cached session expired)" if cached else "logged in fresh (initial auth established)"
            return SessionEstablishResult(auth_result.session_state, False, reason_str)
