"""Recover execution records left behind by API or worker process failures."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.infrastructure.database.session import async_session_factory
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state_machine import InvalidTransitionError, TERMINAL_STATES

logger = logging.getLogger(__name__)
_dispatch_tasks: set[asyncio.Task] = set()

RECOVERY_INTERVAL_SECONDS = 30
DISPATCH_GRACE_SECONDS = 45
ABANDONED_EXECUTION_SECONDS = 660  # worker hard limit (600s) plus cleanup grace


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


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


async def recovery_loop() -> None:
    """Run reconciliation until application shutdown."""
    while True:
        try:
            await reconcile_executions()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Execution reconciliation failed")
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
