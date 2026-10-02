"""Celery task for flow execution.

Runs the flow execution engine in a background worker.
Idempotent: won't re-run terminal executions.
Enforces execution timeout (PRD §22).
"""

import asyncio
import logging
import uuid

from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Task-level timeout: hard kill after 10 minutes (safety net above runner timeout)
TASK_HARD_TIMEOUT = 600


@celery_app.task(bind=True, name="run_execution", max_retries=1, time_limit=TASK_HARD_TIMEOUT)
def run_execution(self, execution_id: str):
    """Execute a flow in the background.

    Args:
        execution_id: The execution ID to run.

    Idempotent: Skips if execution is already terminal (COMPLETED/FAILED/CANCELLED).
    """
    try:
        asyncio.run(_run_execution_async(self, execution_id))
    except SoftTimeLimitExceeded:
        logger.warning("Execution %s hit soft time limit, graceful shutdown", execution_id)


async def _run_execution_async(task, execution_id: str):
    """Async implementation of the execution task."""
    from app.infrastructure.database.session import async_session_factory
    from app.modules.executions.models import ExecutionStatus
    from app.modules.executions.repository import ExecutionEventRepository, ExecutionRepository
    from app.modules.executions.event_service import EventService
    from app.modules.executions.event_types import EventTypes
    from app.modules.flows.repository import FlowRepository
    from app.engine.execution.runner import FlowRunner

    async with async_session_factory() as db:
        exec_repo = ExecutionRepository(db)
        event_repo = ExecutionEventRepository(db)
        event_svc = EventService(db)
        flow_repo = FlowRepository(db)

        # Load execution
        execution = await exec_repo.get_by_id(uuid.UUID(execution_id))
        if execution is None:
            logger.error("Execution %s not found", execution_id)
            raise ValueError(f"Execution {execution_id} not found")

        # Idempotency: skip if already terminal
        terminal_states = {
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.CANCELLED.value,
        }
        if execution.status in terminal_states:
            logger.info(
                "Execution %s already in terminal state %s, skipping",
                execution_id,
                execution.status,
            )
            return {"status": "skipped", "reason": "already_terminal"}

        # Load flow
        flow = await flow_repo.get_by_id(execution.flow_id)
        if flow is None:
            logger.error("Flow %s not found", execution.flow_id)
            raise ValueError(f"Flow {execution.flow_id} not found")

        # Load credentials for this project
        from app.engine.credentials.models import Credential as EngineCredential
        from app.engine.credentials.store import CredentialStore
        from app.modules.credentials.repository import CredentialRepository

        cred_repo = CredentialRepository(db)
        db_credentials = await cred_repo.list_by_project(flow.project_id)
        credential_store = CredentialStore()
        for cred in db_credentials:
            credential_store.add(
                EngineCredential(
                    id=cred.name,
                    email=cred.email,
                    password=cred.password,
                )
            )

        # Load project for target_url
        from app.modules.projects.repository import ProjectRepository
        project_repo = ProjectRepository(db)
        project = await project_repo.get_by_id(flow.project_id)
        target_url = project.base_url if project else ""

        # Transition to QUEUED (re-read to avoid race with other dispatchers)
        current = await exec_repo.get_by_id(execution.id)
        if current and current.status not in terminal_states:
            await exec_repo.update_status(execution.id, ExecutionStatus.QUEUED)
            await db.commit()

        # Honor a cancellation that arrived between dispatch and pickup
        from app.engine.execution.control import is_cancel_requested
        if await is_cancel_requested(execution_id):
            await exec_repo.update_status(execution.id, ExecutionStatus.CANCELLED)
            await event_svc.record_execution_cancelled(execution.id)
            await db.commit()
            logger.info("Execution %s cancelled before start", execution_id)
            return {"status": "cancelled", "execution_id": execution_id}

        # Realtime event recorder callback to stream updates immediately
        async def event_recorder(exec_id: uuid.UUID, event_type: str, payload: dict):
            try:
                await event_repo.create(
                    execution_id=exec_id,
                    event_type=event_type,
                    payload=payload,
                )
                if event_type == EventTypes.EXECUTION_INITIALIZING:
                    await exec_repo.update_status(exec_id, ExecutionStatus.INITIALIZING)
                elif event_type == EventTypes.BROWSER_STARTED:
                    await exec_repo.update_status(exec_id, ExecutionStatus.BROWSER_READY)
                elif event_type == EventTypes.EXECUTION_STARTED:
                    await exec_repo.update_status(exec_id, ExecutionStatus.RUNNING)
                elif event_type == EventTypes.EXECUTION_PAUSED:
                    await exec_repo.update_status(exec_id, ExecutionStatus.PAUSED)
                elif event_type == EventTypes.EXECUTION_HUMAN_CONTROLLED:
                    await exec_repo.update_status(exec_id, ExecutionStatus.HUMAN_CONTROLLED)
                elif event_type == EventTypes.EXECUTION_RESUMED:
                    await exec_repo.update_status(exec_id, ExecutionStatus.RESUMING)
                await db.commit()
            except Exception as ev_err:
                logger.warning("Failed to record event %s: %s", event_type, ev_err)
                try:
                    await db.rollback()
                except Exception:
                    logger.debug("Event recorder rollback failed")

        # Run the execution engine with timeout
        from app.engine.execution.runner import FlowRunner, EXECUTION_TIMEOUT_SECONDS

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

            # Persist any remaining events from the runner
            for evt in result.get("events", []):
                await event_repo.create(
                    execution_id=execution.id,
                    event_type=evt["type"],
                    payload=evt.get("data", {}),
                )

            # Re-read current status — event_recorder may have advanced it
            current = await exec_repo.get_by_id(execution.id)
            current_status = current.status if current else execution.status

            # Update execution status
            if result.get("success"):
                if current_status not in terminal_states:
                    await exec_repo.update_status(execution.id, ExecutionStatus.COMPLETED)
                await event_svc.record_execution_completed(execution.id, result=result)
            else:
                error_code = result.get("error_code", "EXECUTION_ERROR")
                # Re-read in case event_recorder already advanced status
                current = await exec_repo.get_by_id(execution.id)
                current_status = current.status if current else execution.status
                if current_status not in terminal_states:
                    # Map error codes to structured statuses (never mark UNVERIFIED as FAILED)
                    if error_code == "EXECUTION_TIMEOUT":
                        await exec_repo.update_status(
                            execution.id,
                            ExecutionStatus.TIMEOUT,
                            error_code=error_code,
                            error_message=result.get("error", "Execution timed out"),
                        )
                    elif error_code == "UNVERIFIED":
                        await exec_repo.update_status(
                            execution.id,
                            ExecutionStatus.UNVERIFIED,
                            error_code=error_code,
                            error_message=result.get("error", "Actions completed but mission could not be verified"),
                        )
                    elif error_code == "AUTH_BLOCKED":
                        await exec_repo.update_status(
                            execution.id,
                            ExecutionStatus.BLOCKED,
                            error_code=error_code,
                            error_message=result.get("error", "Blocked on authentication page"),
                        )
                    else:
                        await exec_repo.update_status(
                            execution.id,
                            ExecutionStatus.FAILED,
                            error_code=error_code,
                            error_message=result.get("error", "Unknown error"),
                        )
                if error_code == "UNVERIFIED":
                    # Terminal, not a failure — still emit failed-style event for observability
                    await event_svc.record_execution_failed(
                        execution.id,
                        error_code=error_code,
                        error_message=result.get("error", "Unverified"),
                    )
                else:
                    await event_svc.record_execution_failed(
                        execution.id,
                        error_code=error_code,
                        error_message=result.get("error", "Unknown error"),
                    )
            await db.commit()

            return {
                "status": "completed" if result.get("success") else "failed",
                "execution_id": execution_id,
            }

        except Exception as e:
            logger.exception("Execution %s failed with exception", execution_id)

            # Roll back any broken session state before attempting recovery
            try:
                await db.rollback()
            except Exception:
                logger.debug("Rollback failed (session may already be clean)")

            # Update status to FAILED
            try:
                current = await exec_repo.get_by_id(execution.id)
                current_status = current.status if current else execution.status
                if current_status not in terminal_states:
                    await exec_repo.update_status(
                        execution.id,
                        ExecutionStatus.FAILED,
                        error_code="EXECUTION_ERROR",
                        error_message=str(e),
                    )
                await event_svc.record_execution_failed(
                    execution.id,
                    error_code="EXECUTION_ERROR",
                    error_message=str(e),
                )
                await db.commit()
            except Exception:
                logger.exception("Failed to persist execution failure for %s", execution_id)

            raise
