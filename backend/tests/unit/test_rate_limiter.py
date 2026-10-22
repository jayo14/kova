"""Tests for rate limiter bucket keys and Redis TTL repair."""
from __future__ import annotations

import pytest

from app.modules.auth.rate_limiter import RateLimiter, token_bucket_key


class _FakeRedis:
    """Minimal async Redis stub supporting incr/ttl/expire."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def ttl(self, key: str) -> int:
        if key not in self.counts:
            return -2
        return self.ttls.get(key, -1)

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self.counts:
            return False
        self.ttls[key] = seconds
        return True


def test_token_bucket_key_hashes_full_token():
    """Tokens sharing a 16-char prefix (JWT headers) get distinct buckets."""
    prefix = "eyJhbGciOiJIUzI1"
    tok_a = f"{prefix}AAAA_payload_a.signature_a"
    tok_b = f"{prefix}BBBB_payload_b.signature_b"
    key_a = token_bucket_key(tok_a)
    key_b = token_bucket_key(tok_b)
    assert key_a != key_b
    assert key_a.startswith("tok_")
    assert len(key_a) == len("tok_") + 64  # sha256 hex digest


def test_token_bucket_key_is_stable():
    """Same token always maps to the same bucket."""
    token = "eyJhbGciOiJIUzI1.eyJzdWIiOiIxIn0.sig"
    assert token_bucket_key(token) == token_bucket_key(token)
    assert token_bucket_key(token) != token_bucket_key(token + "x")


@pytest.mark.asyncio
async def test_redis_ttl_set_on_first_increment():
    """First incr sets the TTL window."""
    fake = _FakeRedis()
    rl = RateLimiter(redis_client=fake)
    allowed, _ = await rl.check_user_rate_limit("user-1", limit=60, window_seconds=60)
    assert allowed is True
    assert fake.ttls["ratelimit:user:user-1"] == 60


@pytest.mark.asyncio
async def test_redis_stuck_key_without_ttl_is_repaired():
    """Key existing without TTL (the original bug) gets a TTL on next check."""
    fake = _FakeRedis()
    # Simulate a stuck key: high count, no TTL
    fake.counts["ratelimit:user:stuck-user"] = 100
    fake.ttls.pop("ratelimit:user:stuck-user", None)
    rl = RateLimiter(redis_client=fake)
    allowed, retry_after = await rl.check_user_rate_limit(
        "stuck-user", limit=60, window_seconds=60
    )
    assert allowed is False
    # TTL was repaired so the key will expire
    assert fake.ttls["ratelimit:user:stuck-user"] == 60
    assert retry_after == 60


@pytest.mark.asyncio
async def test_redis_existing_ttl_is_not_extended():
    """Requests inside an active window don't extend it (fixed window)."""
    fake = _FakeRedis()
    rl = RateLimiter(redis_client=fake)
    await rl.check_user_rate_limit("user-2", limit=60, window_seconds=60)
    # Simulate window almost elapsed
    fake.ttls["ratelimit:user:user-2"] = 5
    allowed, _ = await rl.check_user_rate_limit("user-2", limit=60, window_seconds=60)
    assert allowed is True
    assert fake.ttls["ratelimit:user:user-2"] == 5  # unchanged


@pytest.mark.asyncio
async def test_redis_org_limit_repairs_missing_ttl():
    """Org execution limit also repairs stuck keys."""
    fake = _FakeRedis()
    fake.counts["ratelimit:org_exec:org-1"] = 5
    rl = RateLimiter(redis_client=fake)
    allowed, _ = await rl.check_org_execution_limit(
        "org-1", daily_limit=100, window_seconds=86400
    )
    assert allowed is True
    assert fake.ttls["ratelimit:org_exec:org-1"] == 86400
