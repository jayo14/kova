"""Shared execution dispatch helpers.

Single implementation of Celery-first / asyncio-fallback dispatch used by the
flows, CI, and batch-execution API routes so concurrency guards, error
persistence, and terminal-state checks stay consistent everywhere.
"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

# Strong refs so fire-and-forget dispatch tasks are not GC'd mid-run
_dispatch_tasks: set[asyncio.Task] = set()


async def _celery_active_workers(timeout: float = 0.5) -> dict | None:
    """Return the inspect().ping() dict when at least one Celery worker is online."""
    try:
        from app.workers.celery_app import celery_app

        def _ping():
            inspector = celery_app.control.inspect(timeout=0.2)
            return inspector.ping() if inspector else None

        active_workers = await asyncio.wait_for(asyncio.to_thread(_ping), timeout=timeout)
        if active_workers and isinstance(active_workers, dict) and any(active_workers.values()):
            return active_workers
    except Exception as celery_err:
        logger.warning("Celery inspector error: %s", celery_err)
    return None


async def _mark_dispatch_error(execution_id: str, exc: Exception, *, context: str = "execution") -> None:
    """Persist FAILED/DISPATCH_ERROR on a stuck CREATED/INITIALIZING execution."""
    try:
        from app.infrastructure.database.session import async_session_factory
        from app.modules.executions.models import ExecutionStatus
        from app.modules.executions.repository import ExecutionRepository

        async with async_session_factory() as error_db:
            rec_repo = ExecutionRepository(error_db)
            rec = await rec_repo.get_by_id(uuid.UUID(str(execution_id)))
            if rec and rec.status in {"CREATED", "INITIALIZING"}:
                await rec_repo.update_status(
                    uuid.UUID(str(execution_id)),
                    ExecutionStatus.FAILED,
                    error_code="DISPATCH_ERROR",
                    error_message=f"{context} failed to run: {str(exc)[:500]}",
                )
                await error_db.commit()
    except Exception as update_err:
        logger.error(
            "Failed to update execution %s status on dispatch error: %s",
            execution_id,
            update_err,
        )


async def dispatch_execution(execution_id: str, *, context: str = "execution") -> None:
    """Queue on Celery when a worker is online; else run via asyncio.

    On asyncio-fallback failure, persists FAILED/DISPATCH_ERROR so the execution
    cannot linger in CREATED/INITIALIZING forever.
    """
    try:
        from app.workers.tasks.executions import run_execution

        active_workers = await _celery_active_workers()
        if active_workers:
            await asyncio.to_thread(run_execution.delay, execution_id)
            logger.info(
                "Dispatched execution %s to Celery worker: %s",
                execution_id,
                list(active_workers.keys()),
            )
            return
    except Exception as celery_err:
        logger.warning("Celery dispatch error for execution %s: %s", execution_id, celery_err)

    logger.info(
        "No active Celery worker online; executing %s via background asyncio task",
        execution_id,
    )
    from app.workers.tasks.executions import _run_execution_async

    try:
        await _run_execution_async(None, execution_id)
    except Exception as exc:
        logger.exception("Failed to execute %s in background asyncio task: %s", execution_id, exc)
        await _mark_dispatch_error(execution_id, exc, context=context)


def schedule_dispatch(execution_id: str, *, context: str = "execution") -> asyncio.Task:
    """Create the dispatch task without awaiting it (keeps API response free)."""
    task = asyncio.create_task(dispatch_execution(execution_id, context=context))
    _dispatch_tasks.add(task)
    task.add_done_callback(_dispatch_tasks.discard)
    return task


async def dispatch_batch(
    execution_ids: list[str],
    *,
    parallel: bool = True,
    celery_task_id: str | None = None,
) -> str | None:
    """Dispatch a batch: Celery single task if workers online, else per-ID asyncio.

    Returns the Celery task id when queued on Celery, else None (asyncio fallback).
    """
    try:
        from app.workers.tasks.tasks import run_multiple_executions

        active_workers = await _celery_active_workers()
        if active_workers:
            task = await asyncio.to_thread(run_multiple_executions.delay, execution_ids, parallel)
            task_id = celery_task_id or getattr(task, "id", None) or str(uuid.uuid4())
            logger.info(
                "Dispatched batch executions %s to Celery worker: %s",
                execution_ids,
                list(active_workers.keys()),
            )
            return task_id
    except Exception as exc:
        logger.info("Celery unavailable for batch execution (%s); executing via background asyncio tasks", exc)

    for eid in execution_ids:
        schedule_dispatch(eid)
    return None
