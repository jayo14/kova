"""Celery task for flow execution.

Runs the flow execution engine in a background worker.
Idempotent: won't re-run terminal executions.
Enforces execution timeout (PRD §22).
Supports parallel execution of multiple journeys.
"""

import asyncio
import logging
import uuid

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
    """
    try:
        asyncio.run(_run_multiple_executions_async(self, execution_ids, parallel))
    except SoftTimeLimitExceeded:
        logger.warning("Multiple executions hit soft time limit, graceful shutdown")


async def _run_multiple_executions_async(task, execution_ids: list[str], parallel: bool):
    """Async implementation for running multiple executions."""
    from app.infrastructure.database.session import async_session_factory
    from app.modules.executions.models import ExecutionStatus
    from app.modules.executions.repository import ExecutionEventRepository, ExecutionRepository
    from app.modules.executions.event_service import EventService
    from app.modules.flows.repository import FlowRepository
    from app.engine.execution.runner import FlowRunner, EXECUTION_TIMEOUT_SECONDS

    terminal_states = {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
        ExecutionStatus.CANCELLED.value,
    }

    async def run_single(exec_id_str: str):
        """Run a single execution."""
        async with async_session_factory() as db:
            exec_repo = ExecutionRepository(db)
            event_repo = ExecutionEventRepository(db)
            event_svc = EventService(db)
            flow_repo = FlowRepository(db)

            execution = await exec_repo.get_by_id(uuid.UUID(exec_id_str))
            if execution is None:
                logger.error("Execution %s not found", exec_id_str)
                return {"status": "failed", "execution_id": exec_id_str, "error": "not found"}

            if execution.status in terminal_states:
                logger.info("Execution %s already terminal, skipping", exec_id_str)
                return {"status": "skipped", "execution_id": exec_id_str}

            flow = await flow_repo.get_by_id(execution.flow_id)
            if flow is None:
                logger.error("Flow %s not found", execution.flow_id)
                return {"status": "failed", "execution_id": exec_id_str, "error": "flow not found"}

            from app.engine.credentials.models import Credential as EngineCredential
            from app.engine.credentials.store import CredentialStore
            from app.modules.credentials.repository import CredentialRepository

            cred_repo = CredentialRepository(db)
            db_credentials = await cred_repo.list_by_project(flow.project_id)
            credential_store = CredentialStore()
            for cred in db_credentials:
                credential_store.add(
                    EngineCredential(id=cred.name, email=cred.email, password=cred.password)
                )

            from app.modules.projects.repository import ProjectRepository
            project_repo = ProjectRepository(db)
            project = await project_repo.get_by_id(flow.project_id)
            target_url = project.base_url if project else ""

            current = await exec_repo.get_by_id(execution.id)
            if current and current.status not in terminal_states:
                await exec_repo.update_status(execution.id, ExecutionStatus.QUEUED)
                await db.commit()

            async def event_recorder(exec_id: uuid.UUID, event_type: str, payload: dict):
                try:
                    await event_repo.create(execution_id=exec_id, event_type=event_type, payload=payload)
                    if event_type == "execution.initializing":
                        await exec_repo.update_status(exec_id, ExecutionStatus.INITIALIZING)
                    elif event_type == "browser.started":
                        await exec_repo.update_status(exec_id, ExecutionStatus.BROWSER_READY)
                    elif event_type == "execution.started":
                        await exec_repo.update_status(exec_id, ExecutionStatus.RUNNING)
                    await db.commit()
                except Exception as ev_err:
                    logger.warning("Failed to record event %s: %s", event_type, ev_err)
                    try:
                        await db.rollback()
                    except Exception:
                        pass

            runner = FlowRunner()
            try:
                result = await runner.execute(
                    execution_id=execution.id,
                    flow_steps=flow.steps,
                    success_condition=flow.success_condition,
                    credential_store=credential_store,
                    target_url=target_url,
                    event_recorder=event_recorder,
                    timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
                )

                for evt in result.get("events", []):
                    await event_repo.create(
                        execution_id=execution.id,
                        event_type=evt["type"],
                        payload=evt.get("data", {}),
                    )

                current = await exec_repo.get_by_id(execution.id)
                current_status = current.status if current else execution.status

                if result.get("success"):
                    if current_status not in terminal_states:
                        await exec_repo.update_status(execution.id, ExecutionStatus.COMPLETED)
                    await event_svc.record_execution_completed(execution.id, result=result)
                else:
                    error_code = result.get("error_code", "EXECUTION_ERROR")
                    current = await exec_repo.get_by_id(execution.id)
                    current_status = current.status if current else execution.status
                    if current_status not in terminal_states:
                        if error_code == "EXECUTION_TIMEOUT":
                            await exec_repo.update_status(
                                execution.id, ExecutionStatus.TIMEOUT,
                                error_code=error_code, error_message=result.get("error", "Timed out"),
                            )
                        else:
                            await exec_repo.update_status(
                                execution.id, ExecutionStatus.FAILED,
                                error_code=error_code, error_message=result.get("error", "Unknown"),
                            )
                    await event_svc.record_execution_failed(
                        execution.id, error_code=error_code, error_message=result.get("error", "Unknown"),
                    )
                await db.commit()
                return {"status": "completed" if result.get("success") else "failed", "execution_id": exec_id_str}

            except Exception as e:
                logger.exception("Execution %s failed", exec_id_str)
                try:
                    await db.rollback()
                except Exception:
                    pass
                try:
                    current = await exec_repo.get_by_id(execution.id)
                    current_status = current.status if current else execution.status
                    if current_status not in terminal_states:
                        await exec_repo.update_status(
                            execution.id, ExecutionStatus.FAILED,
                            error_code="EXECUTION_ERROR", error_message=str(e),
                        )
                    await event_svc.record_execution_failed(
                        execution.id, error_code="EXECUTION_ERROR", error_message=str(e),
                    )
                    await db.commit()
                except Exception:
                    logger.exception("Failed to persist failure for %s", exec_id_str)
                return {"status": "failed", "execution_id": exec_id_str, "error": str(e)}

    if parallel:
        logger.info("Running %d executions in parallel", len(execution_ids))
        results = await asyncio.gather(*[run_single(eid) for eid in execution_ids], return_exceptions=True)
    else:
        logger.info("Running %d executions sequentially", len(execution_ids))
        results = []
        for eid in execution_ids:
            result = await run_single(eid)
            results.append(result)

    return {"results": results, "parallel": parallel, "count": len(execution_ids)}
