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
    from app.modules.executions.state_machine import TERMINAL_STATES
    from app.modules.executions.reporting import classify_failure, sanitize_payload, sanitize_text
    from app.modules.flows.repository import FlowRepository
    from app.engine.execution.runner import FlowRunner

    async with async_session_factory() as db:
        exec_repo = ExecutionRepository(db)
        event_repo = ExecutionEventRepository(db)
        event_svc = EventService(db)
        flow_repo = FlowRepository(db)

        exec_uuid = uuid.UUID(execution_id)
        # Load execution
        execution = await exec_repo.get_by_id(exec_uuid, for_update=True)
        if execution is None:
            logger.error("Execution %s not found", execution_id)
            raise ValueError(f"Execution {execution_id} not found")

        # Claim the execution under a row lock before touching credentials or
        # launching Chromium. Duplicate broker deliveries see INITIALIZING (or
        # later) and cannot start a second browser session.
        terminal_states = TERMINAL_STATES
        if execution.status in terminal_states:
            logger.info(
                "Execution %s already in terminal state %s, skipping",
                execution_id,
                execution.status,
            )
            return {"status": "skipped", "reason": "already_terminal"}

        if execution.status not in (ExecutionStatus.CREATED.value, ExecutionStatus.QUEUED.value):
            logger.info("Execution %s is already claimed in %s", execution_id, execution.status)
            return {"status": "skipped", "reason": "already_claimed"}

        if execution.status == ExecutionStatus.CREATED.value:
            await exec_repo.update_status(exec_uuid, ExecutionStatus.QUEUED)
        await exec_repo.update_status(exec_uuid, ExecutionStatus.INITIALIZING)
        await db.commit()

        # Extract snapshot and flow configuration upfront so we never rely on expired ORM attributes
        flow_id = execution.flow_id
        flow_snapshot = execution.flow_snapshot or {}

        # Load flow
        flow = await flow_repo.get_by_id(flow_id)
        if flow is None:
            logger.error("Flow %s not found", flow_id)
            raise ValueError(f"Flow {flow_id} not found")

        flow_steps = flow_snapshot.get("steps", flow.steps)
        success_condition = flow_snapshot.get("success_condition", flow.success_condition)
        preconditions = flow_snapshot.get("preconditions", flow.preconditions)
        dependency_plan = flow_snapshot.get("dependency_plan", [])
        objective = flow_snapshot.get("objective", flow.objective)

        # Load credentials for this project
        from app.engine.credentials.models import Credential as EngineCredential
        from app.engine.credentials.store import CredentialStore
        from app.modules.credentials.repository import CredentialRepository
        from app.modules.credentials.crypto import decrypt_credential

        cred_repo = CredentialRepository(db)
        db_credentials = await cred_repo.list_by_project(flow.project_id)
        credential_store = CredentialStore()
        for cred in db_credentials:
            decrypted_pass = cred.password
            if decrypted_pass and decrypted_pass.startswith("gAAAAA"):
                try:
                    decrypted_pass = decrypt_credential(decrypted_pass)
                except Exception as dec_err:
                    logger.warning("Failed to decrypt password for credential %s: %s", cred.id, dec_err)

            credential_store.add(
                EngineCredential(
                    id=str(cred.id),
                    email=cred.email,
                    password=decrypted_pass,
                )
            )
            if cred.name:
                credential_store.add(EngineCredential(id=cred.name, email=cred.email, password=decrypted_pass))
                credential_store.add(EngineCredential(id=cred.name.lower(), email=cred.email, password=decrypted_pass))
            if not credential_store.has("default"):
                credential_store.add(EngineCredential(id="default", email=cred.email, password=decrypted_pass))
            if not credential_store.has("login"):
                credential_store.add(EngineCredential(id="login", email=cred.email, password=decrypted_pass))

        # Load project for target_url
        from app.modules.projects.repository import ProjectRepository
        project_repo = ProjectRepository(db)
        project = await project_repo.get_by_id(flow.project_id)
        target_url = flow_snapshot.get("target_url", project.base_url if project else "")

        # Resolve organization and enforce concurrent execution quota
        org_id = project.org_id if project else None
        if not org_id and project:
            from app.modules.organizations.repository import OrganizationRepository
            org_repo = OrganizationRepository(db)
            primary_org = await org_repo.get_user_primary_org(project.user_id)
            org_id = primary_org.id if primary_org else None

        from app.modules.organizations.service import OrganizationService
        org_service = OrganizationService(db) if org_id else None
        slot_acquired = False
        if org_service and org_id:
            slot_acquired = await org_service.acquire_execution_slot(org_id, queue_timeout=300)
            if not slot_acquired:
                logger.warning("Org %s at capacity, failing execution %s", org_id, execution_id)
                await exec_repo.update_status(
                    exec_uuid,
                    ExecutionStatus.FAILED,
                    error_code="ORG_AT_CAPACITY",
                    error_message="Organization concurrent execution quota exceeded (org_at_capacity)",
                )
                await event_svc.record(exec_uuid, EventTypes.EXECUTION_FAILED, {"error": "org_at_capacity"})
                await db.commit()
                return {"status": "failed", "reason": "org_at_capacity"}

        # Honor a cancellation that arrived between dispatch and pickup
        from app.engine.execution.control import is_cancel_requested
        if await is_cancel_requested(execution_id):
            current = await exec_repo.get_by_id(exec_uuid)
            if current and current.status not in terminal_states:
                await exec_repo.update_status(exec_uuid, ExecutionStatus.CANCELLED)
            await event_svc.record_execution_cancelled(exec_uuid)
            await db.commit()
            if slot_acquired and org_service and org_id:
                await org_service.release_execution_slot(org_id)
            logger.info("Execution %s cancelled before start", execution_id)
            return {"status": "cancelled", "execution_id": execution_id}

        # Realtime event recorder callback to stream updates immediately without racing outer session
        emit_lock = asyncio.Lock()

        async def event_recorder(target_exec_id: uuid.UUID, event_type: str, payload: dict):
            async with emit_lock:
                try:
                    from app.infrastructure.database.session import async_session_factory
                    async with async_session_factory() as event_db:
                        rec_event_repo = ExecutionEventRepository(event_db)
                        rec_exec_repo = ExecutionRepository(event_db)
                        await rec_event_repo.create(
                            execution_id=target_exec_id,
                            event_type=event_type,
                            payload=sanitize_payload(payload),
                        )
                        current_rec = await rec_exec_repo.get_by_id(target_exec_id)
                        current_status = current_rec.status if current_rec else None
                        if event_type == EventTypes.EXECUTION_INITIALIZING and current_status != ExecutionStatus.INITIALIZING.value:
                            await rec_exec_repo.update_status(target_exec_id, ExecutionStatus.INITIALIZING)
                        elif event_type == EventTypes.BROWSER_STARTED:
                            await rec_exec_repo.update_status(target_exec_id, ExecutionStatus.BROWSER_READY)
                        elif event_type == EventTypes.EXECUTION_STARTED:
                            await rec_exec_repo.update_status(target_exec_id, ExecutionStatus.RUNNING)
                        elif event_type == EventTypes.EXECUTION_PAUSED:
                            await rec_exec_repo.update_status(target_exec_id, ExecutionStatus.PAUSED)
                        elif event_type == EventTypes.EXECUTION_HUMAN_CONTROLLED:
                            await rec_exec_repo.update_status(target_exec_id, ExecutionStatus.HUMAN_CONTROLLED)
                        elif event_type == EventTypes.EXECUTION_RESUMED:
                            await rec_exec_repo.update_status(target_exec_id, ExecutionStatus.RESUMING)
                        await event_db.commit()
                except Exception as ev_err:
                    logger.warning("Failed to record event %s: %s", event_type, ev_err)

        # Run the execution engine with timeout
        from app.engine.execution.runner import FlowRunner, EXECUTION_TIMEOUT_SECONDS

        runner = FlowRunner()

        try:
            result = await runner.execute(
                execution_id=exec_uuid,
                flow_steps=flow_steps,
                success_condition=success_condition,
                preconditions=preconditions,
                dependency_plan=dependency_plan,
                credential_store=credential_store,
                target_url=target_url,
                event_recorder=event_recorder,
                timeout_seconds=EXECUTION_TIMEOUT_SECONDS,
                objective=objective,
            )

            # Persist any remaining events from the runner
            for evt in result.get("events", []):
                try:
                    await event_repo.create(
                        execution_id=exec_uuid,
                        event_type=evt["type"],
                        payload=evt.get("data", {}),
                    )
                except Exception:
                    pass

            # Re-read current status — event_recorder may have advanced it
            current = await exec_repo.get_by_id(exec_uuid)
            current_status = current.status if current else None

            # Update execution status
            persisted_result = False
            if result.get("success"):
                if current_status not in terminal_states:
                    await exec_repo.update_status(exec_uuid, ExecutionStatus.COMPLETED)
                    persisted_result = True
                if persisted_result:
                    await event_svc.record_execution_completed(
                        exec_uuid, result=sanitize_payload(result)
                    )
            else:
                error_code = result.get("error_code", "EXECUTION_ERROR")
                # Re-read in case event_recorder already advanced status
                current = await exec_repo.get_by_id(exec_uuid)
                current_status = current.status if current else None
                if current_status not in terminal_states:
                    # Map error codes to structured statuses (never mark UNVERIFIED as FAILED)
                    if error_code == "EXECUTION_TIMEOUT":
                        await exec_repo.update_status(
                            exec_uuid,
                            ExecutionStatus.TIMEOUT,
                            error_code=error_code,
                            error_message=sanitize_text(result.get("error", "Execution timed out")),
                            failure_category="execution_timeout",
                        )
                    elif error_code == "UNVERIFIED":
                        await exec_repo.update_status(
                            exec_uuid,
                            ExecutionStatus.UNVERIFIED,
                            error_code=error_code,
                            error_message=sanitize_text(result.get("error", "Actions completed but mission could not be verified")),
                            failure_category="verification_inconclusive",
                        )
                    elif error_code in ("AUTH_BLOCKED", "PREREQUISITE_UNSATISFIED"):
                        await exec_repo.update_status(
                            exec_uuid,
                            ExecutionStatus.BLOCKED,
                            error_code=error_code,
                            error_message=sanitize_text(result.get("error", "Blocked on authentication page")),
                            failure_category=classify_failure(error_code),
                        )
                    else:
                        failure_category = classify_failure(error_code)
                        terminal_status = (
                            ExecutionStatus.ERROR
                            if error_code in {
                                "BROWSER_START_FAILED", "PAGE_LOAD_FAILED", "ACTION_FAILED",
                                "NETWORK_ERROR", "RESOURCE_LIMIT", "UNKNOWN", "EXECUTION_ERROR",
                            }
                            else ExecutionStatus.FAILED
                        )
                        await exec_repo.update_status(
                            exec_uuid,
                            terminal_status,
                            error_code=error_code,
                            error_message=sanitize_text(result.get("error", "Unknown error")),
                            failure_category=failure_category,
                        )
                    persisted_result = True
                if persisted_result and error_code == "UNVERIFIED":
                    # Terminal, not a failure — still emit failed-style event for observability
                    await event_svc.record_execution_failed(
                        exec_uuid,
                        error_code=error_code,
                        error_message=sanitize_text(result.get("error", "Unverified")),
                    )
                elif persisted_result:
                    await event_svc.record_execution_failed(
                        exec_uuid,
                        error_code=error_code,
                        error_message=sanitize_text(result.get("error", "Unknown error")),
                    )
            await db.commit()

            final_execution = await exec_repo.get_by_id(exec_uuid)
            final_status = final_execution.status if final_execution else "FAILED"

            return {
                "status": final_status.lower(),
                "execution_id": execution_id,
            }

        except Exception as e:
            logger.error("Execution %s failed with %s", execution_id, type(e).__name__)

            # Persist unexpected worker failures distinctly from application assertions using a clean session.
            try:
                from app.infrastructure.database.session import async_session_factory
                async with async_session_factory() as fail_db:
                    fail_exec_repo = ExecutionRepository(fail_db)
                    fail_event_svc = EventService(fail_db)
                    current_rec = await fail_exec_repo.get_by_id(exec_uuid)
                    current_status = current_rec.status if current_rec else None
                    if current_status not in terminal_states:
                        await fail_exec_repo.update_status(
                            exec_uuid,
                            ExecutionStatus.ERROR,
                            error_code="EXECUTION_ERROR",
                            error_message="Execution failed unexpectedly",
                            failure_category="internal_kova",
                        )
                        await fail_event_svc.record_execution_failed(
                            exec_uuid,
                            error_code="EXECUTION_ERROR",
                            error_message="Execution failed unexpectedly",
                        )
                        await fail_db.commit()
            except Exception:
                logger.exception("Failed to persist execution failure for %s", execution_id)

            raise
        finally:
            if slot_acquired and org_service and org_id:
                try:
                    await org_service.release_execution_slot(org_id)
                except Exception as rel_err:
                    logger.warning("Failed to release execution slot for org %s: %s", org_id, rel_err)
