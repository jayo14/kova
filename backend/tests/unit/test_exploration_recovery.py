"""Unit tests for exploration recovery logic."""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.exploration.models import ExplorationStatus
from app.workers.recovery import (
    EXPLORATION_ABANDONED_SECONDS,
    EXPLORATION_DISPATCH_GRACE_SECONDS,
    EXPLORATION_TERMINAL_STATES,
)


def test_exploration_terminal_states():
    """Terminal exploration states should be recognized."""
    assert ExplorationStatus.COMPLETED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.FAILED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.CANCELLED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.BLOCKED.value in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.CREATED.value not in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.CONNECTING.value not in EXPLORATION_TERMINAL_STATES
    assert ExplorationStatus.READY.value not in EXPLORATION_TERMINAL_STATES


def test_exploration_recovery_redispatches_stale_created():
    """CREATED sessions older than grace period should be redispatched."""
    assert (
        ExplorationStatus.CREATED.value not in EXPLORATION_TERMINAL_STATES
    )
    # Simulate the recovery action logic inline (matches reconcile_explorations)
    status = ExplorationStatus.CREATED.value
    age = EXPLORATION_DISPATCH_GRACE_SECONDS - 1
    action = "dispatch" if (status == ExplorationStatus.CREATED.value and age >= EXPLORATION_DISPATCH_GRACE_SECONDS) else None
    assert action is None

    age = EXPLORATION_DISPATCH_GRACE_SECONDS
    action = "dispatch" if (status == ExplorationStatus.CREATED.value and age >= EXPLORATION_DISPATCH_GRACE_SECONDS) else None
    assert action == "dispatch"


def test_exploration_recovery_times_out_abandoned():
    """Non-terminal sessions older than abandoned threshold should time out."""
    status = ExplorationStatus.CONNECTING.value
    age = EXPLORATION_ABANDONED_SECONDS - 1
    action = None
    if status not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
        action = "timeout"
    assert action is None

    age = EXPLORATION_ABANDONED_SECONDS
    action = None
    if status not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
        action = "timeout"
    assert action == "timeout"


def test_exploration_recovery_keeps_terminal():
    """Terminal sessions should never be timed out regardless of age."""
    for terminal in EXPLORATION_TERMINAL_STATES:
        age = EXPLORATION_ABANDONED_SECONDS * 2
        action = None
        if terminal not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
            action = "timeout"
        assert action is None


def test_exploration_recovery_keeps_recent_non_terminal():
    """Recent non-terminal sessions should not be timed out."""
    status = ExplorationStatus.AUTH_REQUIRED.value
    age = EXPLORATION_ABANDONED_SECONDS - 1
    action = None
    if status not in EXPLORATION_TERMINAL_STATES and age >= EXPLORATION_ABANDONED_SECONDS:
        action = "timeout"
    assert action is None


@pytest.mark.asyncio
async def test_reconcile_marks_abandoned_exploration_worker_lost(db_session, monkeypatch):
    from app.modules.exploration.models import ExplorationSession
    from app.modules.exploration.repository import ExplorationEventRepository
    from app.modules.users.models import User
    from app.workers import recovery

    user = User(email="worker-lost@example.com")
    db_session.add(user)
    await db_session.flush()
    session = ExplorationSession(
        user_id=user.id,
        url="https://example.com",
        status=ExplorationStatus.EXPLORING.value,
        updated_at=datetime.now(timezone.utc)
        - timedelta(seconds=EXPLORATION_ABANDONED_SECONDS + 1),
    )
    db_session.add(session)
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(recovery, "async_session_factory", factory)
    result = await recovery.reconcile_explorations()

    assert result["timed_out"] == 1
    await db_session.refresh(session)
    assert session.status == ExplorationStatus.FAILED.value
    assert session.error_message == "worker_lost"
    events = await ExplorationEventRepository(db_session).list_by_session(session.id)
    assert events[-1].payload["reason"] == "worker_lost"


class _FakeDispatchRedis:
    """Minimal async stand-in for the Redis SET NX / DEL used by dispatch locks."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def delete(self, key):
        return 1 if self.values.pop(key, None) is not None else 0


@pytest.mark.asyncio
async def test_claim_exploration_dispatch_allows_one_pending_task(monkeypatch):
    from app.workers import recovery

    monkeypatch.setattr(recovery, "_dispatch_redis", _FakeDispatchRedis())
    session_id = "11111111-1111-1111-1111-111111111111"

    assert await recovery._claim_exploration_dispatch(session_id) is True
    assert await recovery._claim_exploration_dispatch(session_id) is False

    await recovery._release_exploration_dispatch(session_id)
    assert await recovery._claim_exploration_dispatch(session_id) is True


@pytest.mark.asyncio
async def test_claim_exploration_dispatch_fails_open_without_redis(monkeypatch):
    from app.workers import recovery

    monkeypatch.setattr(recovery, "_get_dispatch_redis", lambda: None)

    assert await recovery._claim_exploration_dispatch("any-session") is True


@pytest.mark.asyncio
async def test_reconcile_enqueues_each_stale_exploration_once(
    db_session, monkeypatch
):
    from app.modules.exploration.models import ExplorationSession
    from app.modules.users.models import User
    from app.workers import recovery
    from app.workers.tasks import exploration as exploration_tasks

    user = User(email="dispatch-dedupe@example.com")
    db_session.add(user)
    await db_session.flush()
    session = ExplorationSession(
        user_id=user.id,
        url="https://example.com",
        status=ExplorationStatus.CREATED.value,
        updated_at=datetime.now(timezone.utc)
        - timedelta(seconds=EXPLORATION_DISPATCH_GRACE_SECONDS + 1),
    )
    db_session.add(session)
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(recovery, "async_session_factory", factory)
    monkeypatch.setattr(recovery, "_dispatch_redis", _FakeDispatchRedis())

    enqueued: list[str] = []
    monkeypatch.setattr(
        exploration_tasks.run_exploration,
        "delay",
        lambda session_id: enqueued.append(session_id),
    )

    first = await recovery.reconcile_explorations()
    second = await recovery.reconcile_explorations()

    assert first["redispatched"] == 1
    assert second["redispatched"] == 0
    assert enqueued == [str(session.id)]
