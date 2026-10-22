"""Celery task for flow execution.

Runs the flow execution engine in a background worker.
Idempotent: won't re-run terminal executions.
Enforces execution timeout (PRD §22).
Supports parallel execution of multiple journeys.
"""

import asyncio
import logging

from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app

# Import all models so SQLAlchemy resolves relationships before tasks run
import app.modules.projects.models  # noqa: F401
import app.modules.flows.models  # noqa: F401
import app.modules.executions.models  # noqa: F401
import app.modules.credentials.models  # noqa: F401
import app.modules.users.models  # noqa: F401

logger = logging.getLogger(__name__)

# Task-level timeout: hard kill after 10 minutes (safety net above runner timeout)
TASK_HARD_TIMEOUT = 600

# Single run_execution lives in app.workers.tasks.executions (imported by flows.py).
# Do not redefine it here — Celery name collision would drop one registration.


@celery_app.task(bind=True, name="run_multiple_executions", max_retries=1, time_limit=TASK_HARD_TIMEOUT)
def run_multiple_executions(self, execution_ids: list[str], parallel: bool = True):
    """Execute multiple flows in parallel or sequentially.

    Args:
        execution_ids: List of execution IDs to run.
        parallel: If True, run all executions concurrently. If False, run sequentially.

    Idempotent: Skips executions already in terminal states.
    Delegates each execution to executions._run_execution_async so batch runs
    honor org slots, flow snapshots, objectives, and failure classification.
    """
    try:
        asyncio.run(_run_multiple_executions_async(self, execution_ids, parallel))
    except SoftTimeLimitExceeded:
        logger.warning("Multiple executions hit soft time limit, graceful shutdown")


async def _run_multiple_executions_async(task, execution_ids: list[str], parallel: bool):
    """Async implementation: delegate each execution to the full single-run task."""
    from app.workers.tasks.executions import _run_execution_async

    async def run_single(exec_id_str: str):
        try:
            return await _run_execution_async(None, exec_id_str)
        except ValueError as not_found:
            # _run_execution_async raises ValueError for unknown execution ids
            logger.error("Execution %s not found in batch: %s", exec_id_str, not_found)
            return {"status": "failed", "execution_id": exec_id_str, "error": str(not_found)}
        except Exception as exc:
            logger.exception("Execution %s failed in batch", exec_id_str)
            return {"status": "failed", "execution_id": exec_id_str, "error": str(exc)}

    if parallel:
        logger.info("Running %d executions in parallel", len(execution_ids))
        results = await asyncio.gather(*[run_single(eid) for eid in execution_ids], return_exceptions=True)
    else:
        logger.info("Running %d executions sequentially", len(execution_ids))
        results = []
        for eid in execution_ids:
            results.append(await run_single(eid))

    return {"results": results, "parallel": parallel, "count": len(execution_ids)}
