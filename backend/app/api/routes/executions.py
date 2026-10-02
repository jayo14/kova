"""Execution API endpoints.

Handles execution lifecycle: create, get, cancel, events.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.executions.event_service import EventService
from app.modules.executions.models import ExecutionStatus
from app.modules.executions.schemas import ExecutionCreate, ExecutionEventRead, ExecutionRead
from app.modules.executions.service import ExecutionService
from app.modules.flows.models import Flow
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User

router = APIRouter(prefix="/executions", tags=["executions"])

logger = logging.getLogger(__name__)


class EventCreate(BaseModel):
    event_type: str
    payload: dict | None = None


class ExecutionCancelResponse(BaseModel):
    id: uuid.UUID
    status: str
    message: str


async def _verify_execution_ownership(
    db: AsyncSession, execution_id: uuid.UUID, user_id: uuid.UUID
):
    """Verify an execution exists and belongs to the user via flow → project ownership."""
    from app.modules.executions.repository import ExecutionRepository
    exec_repo = ExecutionRepository(db)
    execution = await exec_repo.get_by_id(execution_id)
    if execution is None:
        return None

    # Check flow → project ownership
    result = await db.execute(select(Flow).where(Flow.id == execution.flow_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        return None

    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id_and_user(flow.project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    return execution


@router.post("/", response_model=ExecutionRead, status_code=201)
async def create_execution(
    data: ExecutionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a new execution for a flow.

    The execution is created in CREATED status.
    Use POST /flows/{flow_id}/executions to create and enqueue.
    """
    # Validate FK: flow must exist and user must own it via project
    result = await db.execute(select(Flow).where(Flow.id == data.flow_id))
    flow = result.scalar_one_or_none()
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id_and_user(flow.project_id, user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    service = ExecutionService(db)
    return await service.create_execution(data)


class BatchExecutionRequest(BaseModel):
    execution_ids: list[str]
    parallel: bool = True


class BatchExecutionResponse(BaseModel):
    results: list[dict]
    parallel: bool
    count: int


@router.post("/batch", response_model=BatchExecutionResponse)
async def run_batch_executions(
    data: BatchExecutionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Run multiple executions in parallel or sequentially.

    Args:
        data: Contains list of execution IDs and parallel flag.
    """
    from app.workers.tasks.tasks import run_multiple_executions

    # Verify ownership of all executions
    for exec_id_str in data.execution_ids:
        try:
            execution = await _verify_execution_ownership(db, uuid.UUID(exec_id_str), user.id)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid execution ID: {exec_id_str}")
        if execution is None:
            raise HTTPException(status_code=404, detail=f"Execution {exec_id_str} not found")

    # Dispatch batch task
    task = run_multiple_executions.delay(data.execution_ids, data.parallel)

    return BatchExecutionResponse(
        results=[{"execution_id": eid, "task_id": task.id} for eid in data.execution_ids],
        parallel=data.parallel,
        count=len(data.execution_ids),
    )


@router.get("/{execution_id}", response_model=ExecutionRead)
async def get_execution(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get execution by ID."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.get("/", response_model=list[ExecutionRead])
async def list_executions(
    flow_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List executions, optionally filtered by flow_id."""
    service = ExecutionService(db)
    if flow_id:
        # Verify user owns the flow
        from app.modules.flows.repository import FlowRepository
        flow_repo = FlowRepository(db)
        flow = await flow_repo.get_by_id(flow_id)
        if flow is None:
            return []
        project_repo = ProjectRepository(db)
        project = await project_repo.get_by_id_and_user(flow.project_id, user.id)
        if project is None:
            return []
        return await service.list_executions(flow_id, skip=skip, limit=limit)

    # List all executions for user's flows
    from app.modules.flows.repository import FlowRepository
    flow_repo = FlowRepository(db)
    project_repo = ProjectRepository(db)

    # Get all user's project IDs
    projects = await project_repo.list_by_user(user.id, limit=1000)
    project_ids = {p.id for p in projects}
    if not project_ids:
        return []

    # Get all flows for user's projects
    from app.modules.flows.models import Flow as FlowModel
    flows_result = await db.execute(
        select(FlowModel).where(FlowModel.project_id.in_(project_ids))
    )
    flows = list(flows_result.scalars().all())
    flow_ids = [f.id for f in flows]
    if not flow_ids:
        return []

    # Get all executions for user's flows
    from app.modules.executions.models import Execution as ExecutionModel
    exec_result = await db.execute(
        select(ExecutionModel)
        .where(ExecutionModel.flow_id.in_(flow_ids))
        .offset(skip)
        .limit(limit)
    )
    return list(exec_result.scalars().all())


@router.post("/{execution_id}/cancel", response_model=ExecutionCancelResponse)
async def cancel_execution(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Cancel an execution.

    Only works if execution is in a non-terminal state.
    """
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    # Check if already terminal
    terminal_states = {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
        ExecutionStatus.CANCELLED.value,
    }
    if execution.status in terminal_states:
        raise HTTPException(
            status_code=409,
            detail=f"Execution is already in terminal state: {execution.status}",
        )

    # Cancel the execution
    service = ExecutionService(db)
    await service.cancel_execution(uuid.UUID(execution_id))

    # Notify the running worker through the Redis control channel so the runner
    # stops at the next step boundary and cleans the browser up. DB-only status
    # changes left orphaned Chromium processes running until timeout.
    try:
        from app.engine.execution.control import request_cancel
        await request_cancel(str(execution_id))
    except Exception as cancel_err:
        # DB status is already CANCELLED; a missed control signal only means
        # the runner will finish or hit its timeout — never a wrong status.
        logger.warning("Cancel signal delivery failed for %s: %s", execution_id, cancel_err)

    return ExecutionCancelResponse(
        id=uuid.UUID(execution_id),
        status=ExecutionStatus.CANCELLED.value,
        message="Execution cancelled",
    )


@router.get("/{execution_id}/events", response_model=list[ExecutionEventRead])
async def get_execution_events(
    execution_id: str,
    skip: int = 0,
    limit: int = 1000,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get events for an execution."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    service = EventService(db)
    return await service.get_events(uuid.UUID(execution_id), skip=skip, limit=limit)


@router.get("/{execution_id}/events/stream")
async def stream_execution_events(
    execution_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Server-Sent Events (SSE) live event stream for execution updates."""
    try:
        parsed_id = uuid.UUID(execution_id)
        execution = await _verify_execution_ownership(db, parsed_id, user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    last_event_id_header = request.headers.get("Last-Event-ID")

    async def event_generator() -> AsyncGenerator[str, None]:
        from app.infrastructure.database.session import async_session_factory
        from app.modules.executions.repository import ExecutionRepository, ExecutionEventRepository

        seen_event_ids: set[uuid.UUID] = set()
        if last_event_id_header:
            try:
                seen_event_ids.add(uuid.UUID(last_event_id_header))
            except Exception:
                logger.debug("Invalid Last-Event-ID header: %s", last_event_id_header)

        ping_counter = 0

        try:
            while True:
                if await request.is_disconnected():
                    break

                async with async_session_factory() as poll_db:
                    event_repo = ExecutionEventRepository(poll_db)
                    exec_repo = ExecutionRepository(poll_db)

                    # Fetch all events for this execution ordered by created_at
                    events = await event_repo.list_by_execution(parsed_id, limit=500)
                    for ev in events:
                        if ev.id not in seen_event_ids:
                            seen_event_ids.add(ev.id)
                            data_payload = {
                                "id": str(ev.id),
                                "execution_id": str(ev.execution_id),
                                "event_type": ev.event_type,
                                "payload": ev.payload,
                                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                            }
                            yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {json.dumps(data_payload)}\n\n"

                    # Check current execution status
                    current_exec = await exec_repo.get_by_id(parsed_id)
                    if current_exec:
                        terminal_statuses = {
                            ExecutionStatus.COMPLETED.value,
                            ExecutionStatus.FAILED.value,
                            ExecutionStatus.CANCELLED.value,
                            ExecutionStatus.TIMEOUT.value,
                        }
                        if current_exec.status in terminal_statuses:
                            yield "event: done\ndata: {}\n\n"
                            break

                    # Heartbeat every ~15s (30 * 0.5s) — must stay inside the loop
                    ping_counter += 1
                    if ping_counter >= 30:
                        ping_counter = 0
                        yield ": ping\n\n"

                await asyncio.sleep(0.5)

        except Exception as e:
            logger.error("Execution SSE generator error for %s: %s", execution_id, e)
            error_payload = {
                "execution_id": execution_id,
                "event_type": "error",
                "payload": {"message": "Stream interrupted due to internal error"},
                "created_at": None,
            }
            yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Evidence Endpoints ────────────────────────────────────────────


@router.get("/{execution_id}/evidence")
async def list_execution_evidence(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List all evidence for an execution.

    Returns evidence metadata with signed URLs for artifact access.
    """
    try:
        exec_uuid = uuid.UUID(execution_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid execution ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.modules.executions.evidence_service import EvidenceService
    evidence_service = EvidenceService(db)
    evidence_list = await evidence_service.get_evidence_list(exec_uuid)

    return evidence_list


@router.get("/{execution_id}/evidence/{evidence_id}")
async def get_execution_evidence(
    execution_id: str,
    evidence_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get a single evidence item with signed URL for artifact access."""
    try:
        exec_uuid = uuid.UUID(execution_id)
        ev_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.modules.executions.evidence_service import EvidenceService
    evidence_service = EvidenceService(db)
    evidence = await evidence_service.get_evidence(ev_uuid)

    if evidence is None or evidence.get("execution_id") != str(exec_uuid):
        raise HTTPException(status_code=404, detail="Evidence not found")

    return evidence


@router.get("/{execution_id}/evidence/{evidence_id}/file")
async def get_evidence_file(
    execution_id: str,
    evidence_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Serve evidence screenshot file directly from storage (owner-only)."""
    try:
        exec_uuid = uuid.UUID(execution_id)
        ev_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Evidence not found")

    from app.modules.executions.evidence_service import EvidenceService
    from app.engine.browser.evidence_storage import evidence_storage

    evidence_service = EvidenceService(db)
    evidence = await evidence_service.get_evidence(ev_uuid)
    if evidence is None or evidence.get("execution_id") != str(exec_uuid):
        raise HTTPException(status_code=404, detail="Evidence not found")

    storage_key = evidence.get("storage_key") or f"{evidence_id}.png"
    signed_url = evidence_storage.create_signed_url(storage_key, str(exec_uuid))
    if not signed_url:
        raise HTTPException(status_code=404, detail="Evidence file not available")

    return RedirectResponse(url=signed_url, status_code=302)


@router.get("/{execution_id}/evidence/{evidence_id}/refresh-url")
async def refresh_evidence_url(
    execution_id: str,
    evidence_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Refresh the signed URL for an evidence item."""
    try:
        exec_uuid = uuid.UUID(execution_id)
        ev_uuid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.modules.executions.evidence_service import EvidenceService
    from app.engine.browser.evidence_storage import evidence_storage

    evidence_service = EvidenceService(db)
    evidence = await evidence_service.get_evidence(ev_uuid)
    if evidence is None or evidence.get("execution_id") != str(exec_uuid):
        raise HTTPException(status_code=404, detail="Evidence not found")

    storage_key = evidence.get("storage_key")
    if not storage_key:
        raise HTTPException(status_code=404, detail="Evidence has no storage key")

    signed_url = evidence_storage.create_signed_url(storage_key, str(exec_uuid))
    if not signed_url:
        raise HTTPException(status_code=500, detail="Could not generate signed URL")

    return {"url": signed_url}

