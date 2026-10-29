"""Unit tests for the exploration dispatch watchdog and queue-depth logging."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.exploration.models import ExplorationSession, ExplorationStatus
from app.modules.exploration.repository import ExplorationEventRepository
from app.modules.users.models import User
from app.workers import recovery
from app.workers.recovery import (
    EXPLORATION_ABANDONED_SECONDS,
    EXPLORATION_DISPATCH_ABANDONED_SECONDS,
    EXPLORATION_DISPATCH_GRACE_SECONDS,
    EXPLORATION_QUEUES,
    _exploration_recovery_action,
)


class _FakeDispatchRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def delete(self, key):
        return 1 if self.values.pop(key, None) is not None else 0


class _FailingDispatchRedis:
    async def set(self, *args, **kwargs):
        raise OSError("Redis unavailable")


class _FakeBrokerRedis:
    def __init__(self, depths: dict[str, int]) -> None:
        self.depths = depths

    async def llen(self, queue):
        return self.depths.get(queue, 0)


@pytest.mark.asyncio
async def test_dispatch_lock_fails_closed_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr(recovery, "_dispatch_redis", _FailingDispatchRedis())

    claimed = await recovery._claim_exploration_dispatch("session-id")

    assert claimed is False


def test_watchdog_ignores_checkpoint_and_terminal_states():
    huge_age = EXPLORATION_ABANDONED_SECONDS * 10
    for status in (
        ExplorationStatus.READY.value,
        ExplorationStatus.AUTH_REQUIRED.value,
        ExplorationStatus.ASKING.value,
        ExplorationStatus.PAUSED.value,
        ExplorationStatus.COMPLETED.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
        ExplorationStatus.BLOCKED.value,
    ):
        assert _exploration_recovery_action(status, huge_age) is None


def test_watchdog_dispatches_created_after_grace():
    created = ExplorationStatus.CREATED.value
    assert (
        _exploration_recovery_action(created, EXPLORATION_DISPATCH_GRACE_SECONDS - 1)
        is None
    )
    assert (
        _exploration_recovery_action(created, EXPLORATION_DISPATCH_GRACE_SECONDS)
        == "dispatch"
    )


def test_watchdog_fails_dispatch_when_queue_never_consumed():
    created = ExplorationStatus.CREATED.value
    assert (
        _exploration_recovery_action(
            created, EXPLORATION_DISPATCH_ABANDONED_SECONDS - 1
        )
        == "dispatch"
    )
    assert (
        _exploration_recovery_action(created, EXPLORATION_DISPATCH_ABANDONED_SECONDS)
        == "fail_dispatch"
    )


def test_watchdog_times_out_running_states():
    assert (
        _exploration_recovery_action(
            ExplorationStatus.CONNECTING.value, EXPLORATION_ABANDONED_SECONDS
        )
        == "timeout"
    )
    assert (
        _exploration_recovery_action(
            ExplorationStatus.AUTHENTICATING.value, EXPLORATION_ABANDONED_SECONDS
        )
        == "timeout"
    )
    assert (
        _exploration_recovery_action(
            ExplorationStatus.CONNECTING.value, EXPLORATION_ABANDONED_SECONDS - 1
        )
        is None
    )


@pytest.mark.asyncio
async def test_reconcile_fails_stuck_created_and_releases_lock(db_session, monkeypatch):
    user = User(email="dispatch-timeout@example.com")
    db_session.add(user)
    await db_session.flush()
    session = ExplorationSession(
        user_id=user.id,
        url="https://example.com",
        status=ExplorationStatus.CREATED.value,
        updated_at=datetime.now(timezone.utc)
        - timedelta(seconds=EXPLORATION_DISPATCH_ABANDONED_SECONDS + 1),
    )
    db_session.add(session)
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(recovery, "async_session_factory", factory)
    redis = _FakeDispatchRedis()
    monkeypatch.setattr(recovery, "_dispatch_redis", redis)
    redis.values[recovery._dispatch_lock_key(str(session.id))] = "1"

    result = await recovery.reconcile_explorations()

    assert result["dispatch_failed"] == 1
    assert result["redispatched"] == 0
    await db_session.refresh(session)
    assert session.status == ExplorationStatus.FAILED.value
    assert session.error_message == "dispatch_timeout"
    assert redis.values == {}

    events = await ExplorationEventRepository(db_session).list_by_session(session.id)
    payload = events[-1].payload
    assert payload["reason"] == "dispatch_timeout"
    assert payload["error_code"] == "DISPATCH_TIMEOUT"


@pytest.mark.asyncio
async def test_reconcile_defers_dispatch_when_lock_redis_fails(db_session, monkeypatch):
    user = User(email="dispatch-redis-down@example.com")
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
    monkeypatch.setattr(recovery, "_dispatch_redis", _FailingDispatchRedis())

    enqueued: list[str] = []
    from app.workers.tasks import exploration as exploration_tasks
    monkeypatch.setattr(
        exploration_tasks.run_exploration,
        "delay",
        lambda session_id: enqueued.append(session_id),
    )

    result = await recovery.reconcile_explorations()

    assert result["redispatched"] == 0
    assert enqueued == []
    await db_session.refresh(session)
    assert session.status == ExplorationStatus.CREATED.value


@pytest.mark.asyncio
async def test_reconcile_keeps_recent_created_queued(db_session, monkeypatch):
    user = User(email="dispatch-recent@example.com")
    db_session.add(user)
    await db_session.flush()
    session = ExplorationSession(
        user_id=user.id,
        url="https://example.com",
        status=ExplorationStatus.CREATED.value,
        updated_at=datetime.now(timezone.utc)
        - timedelta(seconds=EXPLORATION_DISPATCH_GRACE_SECONDS - 1),
    )
    db_session.add(session)
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(recovery, "async_session_factory", factory)
    monkeypatch.setattr(recovery, "_dispatch_redis", _FakeDispatchRedis())

    result = await recovery.reconcile_explorations()

    assert result["dispatch_failed"] == 0
    assert result["redispatched"] == 0
    await db_session.refresh(session)
    assert session.status == ExplorationStatus.CREATED.value


@pytest.mark.asyncio
async def test_log_queue_depths_warns_on_backlog(monkeypatch, caplog):
    monkeypatch.setattr(
        recovery,
        "_get_broker_redis",
        lambda: _FakeBrokerRedis({EXPLORATION_QUEUES[0]: 3}),
    )

    with caplog.at_level(logging.WARNING, logger=recovery.__name__):
        depths = await recovery._log_queue_depths()

    assert depths[EXPLORATION_QUEUES[0]] == 3
    assert any("backlog" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_log_queue_depths_is_quiet_when_empty(monkeypatch, caplog):
    monkeypatch.setattr(
        recovery, "_get_broker_redis", lambda: _FakeBrokerRedis({})
    )

    with caplog.at_level(logging.DEBUG, logger=recovery.__name__):
        depths = await recovery._log_queue_depths()

    assert set(depths) == set(EXPLORATION_QUEUES)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
