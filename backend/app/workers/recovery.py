"""Recover execution and exploration records left behind by API or worker process failures."""

import asyncio
import ssl
import logging
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select

from app.config.settings import settings
from app.infrastructure.database.session import async_session_factory
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state_machine import InvalidTransitionError, TERMINAL_STATES
from app.modules.exploration.models import (
    ExplorationSession,
    ExplorationStatus,
)
from app.modules.exploration.repository import (
    ExplorationEventRepository,
    ExplorationRepository,
)

logger = logging.getLogger(__name__)
_dispatch_tasks: set[asyncio.Task] = set()

RECOVERY_INTERVAL_SECONDS = 30
DISPATCH_GRACE_SECONDS = 45
ABANDONED_EXECUTION_SECONDS = 660  # worker hard limit (600s) plus cleanup grace

EXPLORATION_DISPATCH_GRACE_SECONDS = 45
# A queued exploration that no worker consumed in this window is a lost
# dispatch, not a slow one. Failing it surfaces the outage to the user instead
# of leaving the session pending until the full execution lease expires.
EXPLORATION_DISPATCH_ABANDONED_SECONDS = 300
EXPLORATION_ABANDONED_SECONDS = max(
    660, settings.EXPLORATION_MAX_WALL_CLOCK_SECONDS + 60
)

# One pending Celery task per session. Without this, every reconciliation tick
# re-enqueues the same sessions while no worker is consuming, growing the queue
# without bound.
EXPLORATION_DISPATCH_LOCK_PREFIX = "exploration:dispatch"
EXPLORATION_DISPATCH_LOCK_TTL_SECONDS = EXPLORATION_ABANDONED_SECONDS

_dispatch_redis: aioredis.Redis | None = None
_broker_redis: aioredis.Redis | None = None

EXPLORATION_TERMINAL_STATES = {
    ExplorationStatus.COMPLETED.value,
    ExplorationStatus.FAILED.value,
    ExplorationStatus.CANCELLED.value,
    ExplorationStatus.BLOCKED.value,
}

# States that mean "a Celery task should be consuming this row right now".
EXPLORATION_DISPATCH_STATES = {
    ExplorationStatus.CREATED.value,
    ExplorationStatus.AUTHENTICATING.value,
    ExplorationStatus.DISCOVERING.value,
}

# Durable user checkpoints: the worker intentionally released Chromium and the
# session stays resumable, so recovery must never touch them.
EXPLORATION_CHECKPOINT_STATES = {
    ExplorationStatus.READY.value,
    ExplorationStatus.AUTH_REQUIRED.value,
    ExplorationStatus.ASKING.value,
    ExplorationStatus.PAUSED.value,
}

EXPLORATION_QUEUES = ("kova-free", "kova-pro", "kova-enterprise")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _get_dispatch_redis() -> aioredis.Redis | None:
    """Return a Redis client for dispatch locks, or None when unavailable."""
    global _dispatch_redis
    if _dispatch_redis is not None:
        return _dispatch_redis
    kwargs: dict[str, object] = {
        "decode_responses": True,
        "socket_connect_timeout": 2.0,
        "socket_timeout": 2.0,
    }
    if str(settings.REDIS_URL).startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
    try:
        _dispatch_redis = aioredis.from_url(settings.REDIS_URL, **kwargs)
    except Exception:
        logger.exception("Could not build Redis client for dispatch locks")
        return None
    return _dispatch_redis


def _dispatch_lock_key(session_id: str) -> str:
    return f"{EXPLORATION_DISPATCH_LOCK_PREFIX}:{session_id}"


def _get_broker_redis() -> aioredis.Redis | None:
    """Return a Redis client for the Celery broker, or None when unavailable."""
    global _broker_redis
    if _broker_redis is not None:
        return _broker_redis
    kwargs: dict[str, object] = {
        "decode_responses": True,
        "socket_connect_timeout": 2.0,
        "socket_timeout": 2.0,
    }
    if str(settings.CELERY_BROKER_URL).startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = ssl.CERT_NONE
    try:
        _broker_redis = aioredis.from_url(settings.CELERY_BROKER_URL, **kwargs)
    except Exception:
        logger.exception("Could not build Redis client for the Celery broker")
        return None
    return _broker_redis


async def _log_queue_depths() -> dict[str, int]:
    """Log Celery queue backlog so a stalled worker is visible in the logs.

    A non-empty queue that never drains is the fingerprint of a dead or
    crash-looping worker; without this the only symptom is sessions stuck in
    CREATED.
    """
    client = _get_broker_redis()
    if client is None:
        return {}
    depths: dict[str, int] = {}
    try:
        for queue in EXPLORATION_QUEUES:
            depths[queue] = int(await client.llen(queue))
    except Exception:
        logger.warning("Could not read Celery queue depths", exc_info=True)
        return {}
    if any(depths.values()):
        logger.warning(
            "Celery queue backlog: %s (no worker consuming? check kova-worker)",
            depths,
        )
    else:
        logger.debug("Celery queues empty: %s", depths)
    return depths


async def _claim_exploration_dispatch(session_id: str) -> bool:
    """Claim the single pending dispatch slot for a session.

    Fail closed when the lock service is unavailable. The Celery broker may
    also be unavailable, and enqueuing without deduplication would amplify a
    worker outage into an unbounded queue of duplicate tasks.
    """
    client = _get_dispatch_redis()
    if client is None:
        return False
    try:
        claimed = await client.set(
            _dispatch_lock_key(session_id),
            "1",
            nx=True,
            ex=EXPLORATION_DISPATCH_LOCK_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "Could not claim dispatch lock for exploration %s; deferring dispatch",
            session_id,
            exc_info=True,
        )
        return False
    return bool(claimed)


async def _release_exploration_dispatch(session_id: str) -> None:
    client = _get_dispatch_redis()
    if client is None:
        return
    try:
        await client.delete(_dispatch_lock_key(session_id))
    except Exception:
        logger.warning("Could not release dispatch lock for exploration %s", session_id)


def _release_dispatch_lock_on_failure(session_id: str):
    """Release the dispatch slot when enqueueing fails so the next tick retries."""

    def _callback(task: asyncio.Task) -> None:
        if task.cancelled() or task.exception() is None:
            return
        logger.error(
            "Recovery dispatch failed for exploration %s: %s",
            session_id,
            task.exception(),
        )
        release = asyncio.create_task(_release_exploration_dispatch(session_id))
        _dispatch_tasks.add(release)
        release.add_done_callback(_dispatch_tasks.discard)

    return _callback


PLANNING_TIMEOUT_SECONDS = 30
PREREQUISITE_TIMEOUT_SECONDS = 300  # 5 minutes


def _recovery_action(status: str, age_seconds: float) -> str | None:
    if status in (ExecutionStatus.CREATED.value, ExecutionStatus.QUEUED.value):
        return "dispatch" if age_seconds >= DISPATCH_GRACE_SECONDS else None
    if status == ExecutionStatus.PLANNING.value and age_seconds >= PLANNING_TIMEOUT_SECONDS:
        return "fail_planning"
    if status == ExecutionStatus.RESOLVING_PREREQUISITES.value and age_seconds >= PREREQUISITE_TIMEOUT_SECONDS:
        return "fail_prerequisites"
    if status not in TERMINAL_STATES and age_seconds >= ABANDONED_EXECUTION_SECONDS:
        return "timeout"
    return None


def _exploration_recovery_action(status: str, age_seconds: float) -> str | None:
    """Decide what recovery should do with one exploration session.

    Checkpoints (READY/AUTH_REQUIRED/ASKING/PAUSED) are durable and resumable,
    so recovery never touches them.
    """
    if status in EXPLORATION_TERMINAL_STATES or status in EXPLORATION_CHECKPOINT_STATES:
        return None
    if status in EXPLORATION_DISPATCH_STATES:
        if age_seconds >= EXPLORATION_ABANDONED_SECONDS:
            return "timeout"
        # CREATED means the task was enqueued but never consumed. Retrying is
        # pointless once the dispatch window has passed: nothing will pick it
        # up, so surface the failure instead of leaving the user waiting.
        if (
            status == ExplorationStatus.CREATED.value
            and age_seconds >= EXPLORATION_DISPATCH_ABANDONED_SECONDS
        ):
            return "fail_dispatch"
        if age_seconds >= EXPLORATION_DISPATCH_GRACE_SECONDS:
            return "dispatch"
        return None
    if age_seconds >= EXPLORATION_ABANDONED_SECONDS:
        return "timeout"
    return None


async def reconcile_executions() -> dict[str, int]:
    """Redispatch stale pending rows and terminalize abandoned worker leases."""
    now = datetime.now(timezone.utc)
    dispatch_ids: list[str] = []
    timed_out = 0

    async with async_session_factory() as db:
        result = await db.execute(
            select(Execution).where(
                Execution.status.not_in(TERMINAL_STATES)
            )
        )
        executions = list(result.scalars().all())
        repo = ExecutionRepository(db)

        for execution in executions:
            age = (now - _as_utc(execution.updated_at)).total_seconds()
            action = _recovery_action(execution.status, age)
            if action == "dispatch":
                dispatch_ids.append(str(execution.id))
            elif action in ("fail_planning", "fail_prerequisites"):
                try:
                    is_planning = action == "fail_planning"
                    await repo.update_status(
                        execution.id,
                        ExecutionStatus.FAILED,
                        error_code="PLANNING_TIMEOUT" if is_planning else "PREREQUISITE_TIMEOUT",
                        error_message=(
                            "Execution planning exceeded 30s limit."
                            if is_planning
                            else "Prerequisite resolution exceeded 5m limit."
                        ),
                        failure_category="recovery_timeout",
                    )
                    timed_out += 1
                except InvalidTransitionError:
                    continue
                except Exception:
                    await db.rollback()
                    logger.exception("Failed to fail stuck execution %s in state %s", execution.id, execution.status)
            elif action == "timeout":
                try:
                    await repo.update_status(
                        execution.id,
                        ExecutionStatus.TIMEOUT,
                        error_code="WORKER_LEASE_EXPIRED",
                        error_message="Execution stopped reporting progress and exceeded its worker lease.",
                        failure_category="execution_timeout",
                    )
                    timed_out += 1
                except InvalidTransitionError:
                    # A fresh worker update or cancellation may have won the row lock.
                    continue
                except Exception:
                    await db.rollback()
                    logger.exception("Failed to expire stale execution %s", execution.id)
        await db.commit()

    for execution_id in dispatch_ids:
        try:
            from app.api.routes.flows import _dispatch_execution

            task = asyncio.create_task(_dispatch_execution(execution_id))
            _dispatch_tasks.add(task)
            task.add_done_callback(_dispatch_tasks.discard)
        except Exception:
            logger.exception("Failed to schedule recovery for execution %s", execution_id)

    return {"redispatched": len(dispatch_ids), "timed_out": timed_out}


async def reconcile_explorations() -> dict[str, int]:
    """Redispatch stale pending exploration rows and terminalize abandoned worker leases."""
    now = datetime.now(timezone.utc)
    dispatch_ids: list[str] = []
    release_lock_ids: list[str] = []
    timed_out = 0
    dispatch_failed = 0

    async with async_session_factory() as db:
        result = await db.execute(
            select(ExplorationSession).where(
                ExplorationSession.status.not_in(EXPLORATION_TERMINAL_STATES)
            )
        )
        sessions = list(result.scalars().all())
        repo = ExplorationRepository(db)
        event_repo = ExplorationEventRepository(db)

        for session in sessions:
            age = (now - _as_utc(session.updated_at)).total_seconds()
            action = _exploration_recovery_action(session.status, age)

            if action == "dispatch":
                if await _claim_exploration_dispatch(str(session.id)):
                    dispatch_ids.append(str(session.id))
                else:
                    logger.debug(
                        "Exploration %s already has a pending dispatch", session.id
                    )
            elif action == "fail_dispatch":
                try:
                    await repo.update_status(
                        session.id,
                        ExplorationStatus.FAILED,
                        error_message="dispatch_timeout",
                    )
                    await event_repo.create(
                        exploration_id=session.id,
                        event_type="exploration.failed",
                        payload={
                            "reason": "dispatch_timeout",
                            "error_code": "DISPATCH_TIMEOUT",
                            "waited_seconds": int(age),
                        },
                    )
                    dispatch_failed += 1
                    release_lock_ids.append(str(session.id))
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "Failed to fail undispatched exploration %s", session.id
                    )
            elif action == "timeout":
                try:
                    await repo.update_status(
                        session.id,
                        ExplorationStatus.FAILED,
                        error_message="worker_lost",
                    )
                    await event_repo.create(
                        exploration_id=session.id,
                        event_type="exploration.failed",
                        payload={"reason": "worker_lost"},
                    )
                    timed_out += 1
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "Failed to expire stale exploration %s", session.id
                    )
        await db.commit()

    for session_id in release_lock_ids:
        await _release_exploration_dispatch(session_id)

    for session_id in dispatch_ids:
        try:
            from app.workers.tasks.exploration import run_exploration

            task = asyncio.create_task(
                asyncio.to_thread(run_exploration.delay, session_id)
            )
            _dispatch_tasks.add(task)
            task.add_done_callback(_dispatch_tasks.discard)
            task.add_done_callback(_release_dispatch_lock_on_failure(session_id))
        except Exception:
            await _release_exploration_dispatch(session_id)
            logger.exception(
                "Failed to schedule recovery for exploration %s", session_id
            )

    return {
        "redispatched": len(dispatch_ids),
        "timed_out": timed_out,
        "dispatch_failed": dispatch_failed,
    }


async def recovery_loop() -> None:
    """Run reconciliation until application shutdown."""
    while True:
        try:
            await reconcile_executions()
            await reconcile_explorations()
            await _log_queue_depths()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Recovery reconciliation failed")
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
