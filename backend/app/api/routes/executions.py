"""Execution API endpoints.

Handles execution lifecycle: create, get, cancel, events.
"""

import asyncio
import hashlib
import hmac
import html
import json
import logging
import time
from typing import AsyncGenerator
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.auth.dependencies import get_optional_current_user
from app.modules.executions.event_service import EventService
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.schemas import ExecutionCreate, ExecutionEventRead, ExecutionRead
from app.modules.executions.service import ExecutionService
from app.modules.executions.state_machine import InvalidTransitionError, TERMINAL_STATES

from app.modules.executions.reporting import (
    build_timeline,
    compute_verdict_breakdown,
    derive_report_status,
    diagnose_failure,
    diagnose_verification,
    sanitize_payload,
    sanitize_text,
)
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
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
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a new execution for a flow and schedule dispatch."""
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
    execution = await service.create_execution(data)
    await db.commit()

    from app.api.routes.flows import _schedule_dispatch
    response.background = BackgroundTask(_schedule_dispatch, str(execution.id))
    return execution


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
    # Verify ownership of all executions
    for exec_id_str in data.execution_ids:
        try:
            execution = await _verify_execution_ownership(db, uuid.UUID(exec_id_str), user.id)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid execution ID: {exec_id_str}")
        if execution is None:
            raise HTTPException(status_code=404, detail=f"Execution {exec_id_str} not found")

    # Dispatch batch via shared helper (Celery when workers online, else per-ID asyncio)
    from app.api.dispatch import dispatch_batch

    task_id = await dispatch_batch(data.execution_ids, parallel=data.parallel) or str(uuid.uuid4())

    return BatchExecutionResponse(
        results=[{"execution_id": eid, "task_id": task_id} for eid in data.execution_ids],
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
    from app.modules.executions.state_machine import TERMINAL_STATES
    terminal_states = TERMINAL_STATES
    if execution.status in terminal_states:
        raise HTTPException(
            status_code=409,
            detail=f"Execution is already in terminal state: {execution.status}",
        )

    # Cancel the execution
    service = ExecutionService(db)
    try:
        await service.cancel_execution(uuid.UUID(execution_id))
    except InvalidTransitionError:
        # Completion may have won the race after the initial read.
        raise HTTPException(
            status_code=409,
            detail="Execution state changed before cancellation could be applied",
        )

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


class ExecutionControlResponse(BaseModel):
    execution_id: str
    state: str
    owner: str
    lease_id: str | None = None
    lease_expires_at: float | None = None
    generation: int
    checkpoint: dict | None = None
    updated_at: float


class ExecutionPauseRequest(BaseModel):
    reason: str | None = None


class ExecutionTakeoverRequest(BaseModel):
    lease_duration_seconds: float = 300.0


class ExecutionReleaseRequest(BaseModel):
    lease_id: str | None = None


class ExecutionInteractRequest(BaseModel):
    type: str
    kind: str | None = None
    x: float | None = None
    y: float | None = None
    text: str | None = None
    key: str | None = None
    delta_x: float | None = None
    delta_y: float | None = None
    lease_id: str | None = None
    generation: int | None = None


@router.get("/{execution_id}/control", response_model=ExecutionControlResponse)
async def get_execution_control(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve authoritative control record and human takeover state."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.engine.execution.control import get_control_record
    record = await get_control_record(execution_id)
    return ExecutionControlResponse(**record.to_dict())


@router.post("/{execution_id}/pause", response_model=ExecutionControlResponse)
async def pause_execution_endpoint(
    execution_id: str,
    data: ExecutionPauseRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Request immediate pause of execution at the next action boundary."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status in TERMINAL_STATES:
        raise HTTPException(status_code=409, detail=f"Cannot pause execution in terminal state: {execution.status}")

    from app.engine.execution.control import request_pause
    reason = data.reason if data and data.reason else "User requested pause"
    record = await request_pause(execution_id, reason=reason)
    return ExecutionControlResponse(**record.to_dict())


@router.post("/{execution_id}/resume", response_model=ExecutionControlResponse)
async def resume_execution_endpoint(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Resume execution back to agent control."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status in TERMINAL_STATES:
        raise HTTPException(status_code=409, detail=f"Cannot resume execution in terminal state: {execution.status}")

    from app.engine.execution.control import request_resume
    record = await request_resume(execution_id)
    return ExecutionControlResponse(**record.to_dict())


@router.post("/{execution_id}/takeover", response_model=ExecutionControlResponse)
async def takeover_execution_endpoint(
    execution_id: str,
    data: ExecutionTakeoverRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Acquire exclusive human control lease for the execution browser."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status in TERMINAL_STATES:
        raise HTTPException(status_code=409, detail=f"Cannot take control of terminal execution: {execution.status}")

    from app.engine.execution.control import acquire_human_takeover
    ttl = data.lease_duration_seconds if data else 300.0
    ok, lease_or_err, record = await acquire_human_takeover(
        execution_id,
        client_id=str(user.id),
        lease_duration_seconds=ttl,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=lease_or_err)
    return ExecutionControlResponse(**record.to_dict())


@router.post("/{execution_id}/release", response_model=ExecutionControlResponse)
async def release_execution_control_endpoint(
    execution_id: str,
    data: ExecutionReleaseRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Release human takeover lease and return browser control to agent."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.engine.execution.control import release_human_control
    lease_id = data.lease_id if data else None
    ok, err, record = await release_human_control(
        execution_id,
        client_id=str(user.id),
        lease_id=lease_id,
    )
    if not ok:
        raise HTTPException(status_code=403, detail=err)
    return ExecutionControlResponse(**record.to_dict())


@router.post("/{execution_id}/interact")
async def interact_execution_endpoint(
    execution_id: str,
    data: ExecutionInteractRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Deliver human interaction command (click, type, scroll, key, nav) during takeover."""
    try:
        execution = await _verify_execution_ownership(db, uuid.UUID(execution_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.engine.execution.control import validate_human_interaction, queue_user_input
    ok, err = await validate_human_interaction(
        execution_id,
        lease_id=data.lease_id,
        client_id=str(user.id),
        generation=data.generation,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=err or "Invalid human interaction")

    await queue_user_input(execution_id, data.model_dump(exclude_none=True))
    return {"status": "queued", "message": "Interaction queued"}



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
):
    """Server-Sent Events (SSE) live event stream for execution updates."""
    from app.infrastructure.database.session import async_session_factory

    try:
        parsed_id = uuid.UUID(execution_id)
        async with async_session_factory() as auth_db:
            execution = await _verify_execution_ownership(auth_db, parsed_id, user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid execution ID")
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    last_event_id_header = request.headers.get("Last-Event-ID")

    async def event_generator() -> AsyncGenerator[str, None]:
        from app.modules.executions.repository import ExecutionRepository, ExecutionEventRepository
        from app.modules.executions.state_machine import TERMINAL_STATES

        seen_event_ids: set[uuid.UUID] = set()
        if last_event_id_header:
            try:
                seen_event_ids.add(uuid.UUID(last_event_id_header))
            except Exception:
                logger.debug("Invalid Last-Event-ID header: %s", last_event_id_header)

        ping_counter = 0

        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break

                chunks_to_send: list[str] = []
                is_terminal = False

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
                            chunks_to_send.append(
                                f"id: {ev.id}\nevent: {ev.event_type}\ndata: {json.dumps(data_payload)}\n\n"
                            )

                    # Check current execution status
                    current_exec = await exec_repo.get_by_id(parsed_id)
                    if current_exec and current_exec.status in TERMINAL_STATES:
                        is_terminal = True

                # Yield collected events outside of the database session context
                for chunk in chunks_to_send:
                    yield chunk

                if is_terminal:
                    yield "event: done\ndata: {}\n\n"
                    break

                # Heartbeat every ~15s (30 * 0.5s)
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
    grouped: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List all evidence for an execution, optionally grouped by step_id.

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
    if grouped:
        return await evidence_service.get_evidence_list_grouped_by_step(exec_uuid)
    return await evidence_service.get_evidence_list(exec_uuid)


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


@router.get("/{execution_id}/trace")
@router.get("/{execution_id}/trace/download")
async def get_execution_trace(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Download Playwright trace zip recording directly or via signed URL."""
    import os
    from app.modules.executions.evidence_model import Evidence

    try:
        exec_uuid = uuid.UUID(execution_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid execution ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    # 1. Query evidence table for any recorded trace_url
    ev_stmt = (
        select(Evidence.trace_url)
        .where(Evidence.execution_id == exec_uuid, Evidence.trace_url.isnot(None))
        .order_by(Evidence.created_at.desc())
        .limit(1)
    )
    ev_res = await db.execute(ev_stmt)
    trace_url = ev_res.scalar_one_or_none()

    # 2. If it's an external URL (e.g. S3/R2 presigned or public), redirect
    if trace_url and (trace_url.startswith("http://") or trace_url.startswith("https://")):
        return RedirectResponse(url=trace_url, status_code=302)

    # 3. If it's a local file path recorded against this execution
    local_path = None
    if trace_url:
        cleaned = trace_url.replace("file://", "").strip()
        if os.path.exists(cleaned):
            local_path = cleaned

    if not local_path or not os.path.exists(local_path):
        raise HTTPException(
            status_code=404,
            detail="Trace recording not available for this execution"
        )

    return FileResponse(
        path=local_path,
        media_type="application/zip",
        filename=f"trace_{exec_uuid}.zip",
    )


REPORT_SIGNATURE_TTL_SECONDS = 7 * 86400


def _generate_report_signature(execution_id: uuid.UUID, expires_at: int | None = None) -> str:
    from app.modules.auth.dependencies import _get_jwt_secret
    secret = _get_jwt_secret()
    expires_at = expires_at or int(time.time()) + REPORT_SIGNATURE_TTL_SECONDS
    msg = f"report:{execution_id}:{expires_at}"
    digest = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{expires_at}.{digest}"


def _verify_report_signature(execution_id: uuid.UUID, signature: str) -> bool:
    try:
        expiry_text, supplied = signature.split(".", 1)
        expires_at = int(expiry_text)
    except (ValueError, TypeError):
        return False
    if expires_at < int(time.time()):
        return False
    expected = _generate_report_signature(execution_id, expires_at).split(".", 1)[1]
    return hmac.compare_digest(expected, supplied)


def _render_report_html(
    execution_id: uuid.UUID,
    status_str: str,
    flow_name: str,
    project_name: str,
    duration_str: str,
    verification: dict,
    error_message: str | None = None,
    shareable_url: str = "",
    ai_healed_steps: int = 0,
    why_it_failed: str | None = None,
) -> str:
    passed = verification.get("passed", False)
    checks = verification.get("checks", [])
    badge_color = "#10b981" if (status_str == "COMPLETED" and passed) else ("#ef4444" if status_str == "FAILED" else "#f59e0b")

    why_failed_banner = ""
    if why_it_failed:
        why_failed_banner = f"""
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 8px; padding: 14px 18px; margin-bottom: 20px; color: #fca5a5;">
            <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; color: #f87171; margin-bottom: 4px;">Why it failed</div>
            <div style="font-size: 15px; color: #ffffff; font-weight: 500;">{html.escape(why_it_failed)}</div>
        </div>
        """

    healing_banner = ""
    if ai_healed_steps > 0:
        healing_banner = f"""
        <div style="background: rgba(59, 130, 246, 0.15); border: 1px solid #3b82f6; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; color: #93c5fd; font-weight: 600;">
            Passed with AI healing: {ai_healed_steps} steps
        </div>
        """

    checks_html = ""
    for c in checks:
        c_type = html.escape(str(c.get("type", "unknown")))
        c_passed = c.get("passed", False)
        c_badge = '<span style="color:#10b981;font-weight:600;">PASS</span>' if c_passed else '<span style="color:#ef4444;font-weight:600;">FAIL</span>'
        c_msg = html.escape(str(c.get("message") or ""))
        checks_html += f"""
        <tr style="border-bottom: 1px solid #334155;">
            <td style="padding: 10px; font-family: monospace;">{c_type}</td>
            <td style="padding: 10px;">{c_badge}</td>
            <td style="padding: 10px; color: #94a3b8;">{c_msg}</td>
        </tr>
        """
    if not checks_html:
        checks_html = '<tr><td colspan="3" style="padding: 12px; color: #94a3b8; text-align: center;">No individual verification checks recorded.</td></tr>'

    error_banner = ""
    if error_message:
        error_banner = f"""
        <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; color: #fca5a5;">
            <strong>Error:</strong> {html.escape(error_message)}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kova Execution Report - {html.escape(flow_name)}</title>
    <style>
        body {{
            background-color: #0f172a;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 860px;
            margin: 0 auto;
            background: #1e293b;
            border-radius: 12px;
            border: 1px solid #334155;
            padding: 32px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #334155;
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .badge {{
            background: {badge_color};
            color: #ffffff;
            font-weight: 700;
            font-size: 14px;
            padding: 6px 14px;
            border-radius: 9999px;
            letter-spacing: 0.05em;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
            background: #0f172a;
            padding: 16px;
            border-radius: 8px;
        }}
        .meta-item label {{
            display: block;
            font-size: 12px;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }}
        .meta-item span {{
            font-size: 15px;
            font-weight: 600;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            margin-top: 12px;
        }}
        th {{
            background: #0f172a;
            padding: 10px;
            font-size: 13px;
            color: #94a3b8;
            border-bottom: 2px solid #334155;
        }}
        .footer {{
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid #334155;
            font-size: 12px;
            color: #64748b;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .footer a {{
            color: #38bdf8;
            text-decoration: none;
        }}
        @media print {{
            * {{
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            body {{
                background: #ffffff !important;
                color: #111827 !important;
                padding: 0;
            }}
            .container {{
                background: #ffffff !important;
                border: none;
                box-shadow: none;
                padding: 0;
            }}
            .meta-grid,
            th {{
                background: #f3f4f6 !important;
            }}
            .badge {{
                color: #ffffff !important;
            }}
            tr {{
                break-inside: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1 style="margin: 0; font-size: 24px; color: #f8fafc;">Kova Execution Report</h1>
                <p style="margin: 4px 0 0 0; color: #94a3b8; font-size: 14px;">Flow: <strong>{html.escape(flow_name)}</strong> &bull; Project: <strong>{html.escape(project_name)}</strong></p>
            </div>
            <div class="badge">{html.escape(status_str)}</div>
        </div>

        {why_failed_banner}
        {healing_banner}
        {error_banner}

        <div class="meta-grid">
            <div class="meta-item">
                <label>Execution ID</label>
                <span style="font-family: monospace; font-size: 13px;">{html.escape(str(execution_id)[:8])}...</span>
            </div>
            <div class="meta-item">
                <label>Duration</label>
                <span>{html.escape(duration_str)}</span>
            </div>
            <div class="meta-item">
                <label>Verification</label>
                <span style="color: {'#10b981' if passed else '#ef4444'};">{'PASSED' if passed else ('UNVERIFIED' if status_str == 'UNVERIFIED' else 'FAILED')}</span>
            </div>
        </div>

        <h3 style="margin-top: 24px; margin-bottom: 8px; font-size: 16px;">Verification Checks</h3>
        <table>
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Result</th>
                    <th>Message</th>
                </tr>
            </thead>
            <tbody>
                {checks_html}
            </tbody>
        </table>

        <div class="footer">
            <span>Generated by Kova Deterministic Platform</span>
            <span><a href="{html.escape(shareable_url, quote=True)}">Signed Shareable Link</a></span>
        </div>
    </div>
</body>
</html>"""


@router.get("/{execution_id}/report")
async def get_execution_report(
    execution_id: str,
    request: Request,
    signature: str | None = None,
    format: str | None = None,
    compare_to: str | None = None,
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Return JSON execution report plus a signed, shareable HTML page."""
    try:
        exec_uuid = uuid.UUID(execution_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid execution ID")

    if signature:
        if not _verify_report_signature(exec_uuid, signature):
            raise HTTPException(status_code=401, detail="Invalid report signature")

        from app.modules.validation.models import SignedUrlModel
        su_check = await db.execute(
            select(SignedUrlModel).where(
                SignedUrlModel.execution_id == exec_uuid,
                SignedUrlModel.signature == signature,
            )
        )
        if not su_check.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Signed URL has been revoked")

        stmt = select(Execution).where(Execution.id == exec_uuid)
        res = await db.execute(stmt)
        execution = res.scalar_one_or_none()
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")
    else:
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        execution = await _verify_execution_ownership(db, exec_uuid, user.id)
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

    flow_stmt = select(Flow).where(Flow.id == execution.flow_id)
    flow_res = await db.execute(flow_stmt)
    flow = flow_res.scalar_one_or_none()
    flow_name = flow.name if flow else "Flow"

    project_name = "Project"
    if flow:
        proj_stmt = select(Project).where(Project.id == flow.project_id)
        proj_res = await db.execute(proj_stmt)
        project = proj_res.scalar_one_or_none()
        if project:
            project_name = project.name

    from app.modules.executions.event_service import EventService
    from app.modules.executions.event_types import EventTypes

    event_svc = EventService(db)
    events = await event_svc.get_events(exec_uuid)
    verification_dict = {"passed": False, "checks": []}
    for ev in reversed(events):
        if ev.event_type in (EventTypes.VERIFICATION_PASSED, "verification_passed", EventTypes.VERIFICATION_FAILED, "verification_failed") and isinstance(ev.payload, dict):
            checks = sanitize_payload(ev.payload.get("checks", []))
            verification_dict = {
                **sanitize_payload(ev.payload),
                "checks": checks,
                "passed": ev.event_type in (EventTypes.VERIFICATION_PASSED, "verification_passed")
                and bool(checks)
                and all(check.get("passed") is True for check in checks),
            }
            break

    persisted_status = execution.status.value if hasattr(execution.status, "value") else str(execution.status)
    timeline = build_timeline(
        events,
        execution_status=persisted_status,
        verification_passed=verification_dict.get("passed") is True,
    )
    report_status = derive_report_status(persisted_status, verification_dict)
    diagnostics = diagnose_failure(execution.error_code, execution.error_message)
    if diagnostics is None and not verification_dict.get("passed"):
        failed_checks = [check for check in verification_dict.get("checks", []) if check.get("passed") is False]
        if failed_checks:
            diagnostics = diagnose_verification(failed_checks[0])

    ai_assisted_events = [ev for ev in events if ev.event_type in ("ai_assisted", EventTypes.AI_ASSISTED)]
    healed_steps_count = len(ai_assisted_events)
    healing_summary = f"Passed with AI healing: {healed_steps_count} steps" if healed_steps_count > 0 else None

    from app.modules.executions.evidence_service import EvidenceService
    ev_svc = EvidenceService(db)
    ev_items = await ev_svc.get_evidence_list(exec_uuid)
    evidence_incomplete = any(item.get("status") in ("PENDING", "FAILED") for item in ev_items)
    has_ev_incomplete_event = any(ev.event_type in (EventTypes.EVIDENCE_FAILED, "evidence_failed") for ev in events)
    is_ev_incomplete = evidence_incomplete or has_ev_incomplete_event
    evidence_status_label = "verified, evidence incomplete" if (report_status == ExecutionStatus.COMPLETED.value and is_ev_incomplete) else ("incomplete" if is_ev_incomplete else "complete")

    sig = _generate_report_signature(exec_uuid)
    base_url = str(request.base_url).rstrip("/")
    shareable_url = f"{base_url}/api/v1/executions/{exec_uuid}/report?signature={sig}"

    from app.modules.validation.models import SignedUrlModel
    from datetime import datetime, timezone
    su_check = await db.execute(select(SignedUrlModel).where(SignedUrlModel.signature == sig))
    if not su_check.scalar_one_or_none():
        expiry_ts = int(sig.split(".", 1)[0])
        expires_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
        db.add(
            SignedUrlModel(
                id=uuid.uuid4(),
                execution_id=exec_uuid,
                url=shareable_url,
                signature=sig,
                expires_at=expires_dt,
                created_by=user.id if user else None,
            )
        )
        await db.commit()

    if signature:
        shareable_url = None

    duration_ms = None
    if execution.started_at and execution.completed_at:
        duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
    duration_str = f"{duration_ms} ms" if duration_ms is not None else "N/A"

    is_success = report_status == ExecutionStatus.COMPLETED.value and verification_dict.get("passed", False)
    why_it_failed = None
    if not is_success:
        if execution.error_message:
            why_it_failed = sanitize_text(execution.error_message)
        else:
            failed_checks = [c for c in verification_dict.get("checks", []) if not c.get("passed")]
            if failed_checks:
                c = failed_checks[0]
                exp = c.get("expected")
                act = c.get("actual")
                if exp is not None or act is not None:
                    why_it_failed = sanitize_text(f"Expected {exp!r} for {c.get('type')}, but observed {act!r}.")
                else:
                    why_it_failed = c.get("message") or f"Check {c.get('type')} failed."
            else:
                why_it_failed = "Execution did not complete required verification checks."

    if compare_to:
        try:
            comp_uuid = uuid.UUID(compare_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid comparison execution ID")
        comp_exec_stmt = select(Execution).where(Execution.id == comp_uuid)
        comp_exec_res = await db.execute(comp_exec_stmt)
        comp_exec = comp_exec_res.scalar_one_or_none()
        if not comp_exec:
            raise HTTPException(status_code=404, detail="Comparison execution not found")
        comp_status = comp_exec.status.value if hasattr(comp_exec.status, "value") else str(comp_exec.status)
        diff_html = f"""<!DOCTYPE html>
<html>
<head><title>Execution Diff</title><style>body {{ background: #0f172a; color: #f8fafc; font-family: sans-serif; padding: 24px; }} .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }} .box {{ background: #1e293b; padding: 16px; border-radius: 8px; border: 1px solid #334155; }}</style></head>
<body>
<h2>Execution Diff: {html.escape(flow_name)}</h2>
<div class="grid">
  <div class="box"><h3>Run A ({comp_uuid})</h3><p>Status: {comp_status}</p></div>
  <div class="box"><h3>Run B ({exec_uuid})</h3><p>Status: {report_status}</p></div>
</div>
</body></html>"""
        return HTMLResponse(content=diff_html)

    html_content = _render_report_html(
        execution_id=exec_uuid,
        status_str=report_status,
        flow_name=flow_name,
        project_name=project_name,
        duration_str=duration_str,
        verification=verification_dict,
        error_message=execution.error_message,
        shareable_url=shareable_url or "",
        ai_healed_steps=healed_steps_count,
        why_it_failed=why_it_failed,
    )

    accept_header = request.headers.get("accept", "")
    if signature or format == "html" or ("application/json" not in accept_header and "text/html" in accept_header):
        return HTMLResponse(content=html_content)

    all_checks = verification_dict.get("checks", [])
    verdict_breakdown, total_evaluated = compute_verdict_breakdown(all_checks, timeline)
    declared_planned = len(flow.steps or []) if flow and isinstance(flow.steps, list) else 0
    total_planned = max(declared_planned, total_evaluated)

    recovery_trail = []
    for ev in events:
        if ev.event_type in (
            EventTypes.RECOVERY_STARTED,
            "recovery.started",
            "action.idempotency_halted",
            "human_takeover_started",
            "human_control_released",
            EventTypes.EXECUTION_PAUSED,
            EventTypes.EXECUTION_RESUMED,
        ):
            recovery_trail.append({
                "event_type": ev.event_type,
                "timestamp": ev.created_at.isoformat() if ev.created_at else None,
                "payload": sanitize_payload(ev.payload or {}),
            })

    evidence_references = [
        {
            "id": str(item.get("id")),
            "type": item.get("kind") or item.get("type", "evidence"),
            "title": item.get("title", ""),
            "status": item.get("status", ""),
        }
        for item in ev_items
    ]

    report_response = {
        "execution_id": str(exec_uuid),
        "status": report_status,
        "persisted_status": persisted_status,
        "flow_id": str(execution.flow_id),
        "flow_version": execution.flow_version,
        "flow_name": flow_name,
        "project_name": project_name,
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "duration_ms": duration_ms,
        "error_code": execution.error_code,
        "error_message": sanitize_text(execution.error_message) if execution.error_message else None,
        "why_it_failed": why_it_failed,
        "verification": verification_dict,
        "verdict_breakdown": verdict_breakdown,
        "assertions_summary": {
            "total_planned": total_planned,
            "total_evaluated": total_evaluated,
            **verdict_breakdown,
        },
        "evidence_references": evidence_references,
        "recovery_audit_trail": recovery_trail,
        "failure_category": execution.failure_category or (diagnostics.get("category") if diagnostics else None),
        "diagnosis": diagnostics,
        "steps": timeline,
        "step_counts": {name: sum(1 for step in timeline if step.get("status") == name) for name in ("passed", "failed", "blocked", "unverified", "error")},
        "ai_healed_steps": healed_steps_count,
        "healing_summary": healing_summary,
        "evidence_status": evidence_status_label,
        "evidence_incomplete": is_ev_incomplete,
        "signature": None if signature else sig,
        "shareable_url": None if signature else shareable_url,
    }
    if format == "html":
        return HTMLResponse(content=html_content)
    if format != "json":
        report_response["html"] = html_content
    return report_response


@router.post("/{execution_id}/share")
async def share_execution_report(
    execution_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        exec_uuid = uuid.UUID(execution_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid execution ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.modules.validation.models import SignedUrlModel
    from datetime import datetime, timezone

    sig = _generate_report_signature(exec_uuid)
    base_url = str(request.base_url).rstrip("/")
    shareable_url = f"{base_url}/api/v1/executions/{exec_uuid}/report?signature={sig}"

    expiry_ts = int(sig.split(".", 1)[0])
    expires_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)

    # Persist in SignedUrlModel
    signed_url_record = SignedUrlModel(
        id=uuid.uuid4(),
        execution_id=exec_uuid,
        url=shareable_url,
        signature=sig,
        expires_at=expires_dt,
        created_by=user.id,
    )
    db.add(signed_url_record)
    await db.commit()

    return {
        "url": shareable_url,
        "signature": sig,
        "expires_at": expires_dt.isoformat(),
    }


@router.delete("/{execution_id}/share")
async def revoke_execution_report(
    execution_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        exec_uuid = uuid.UUID(execution_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid execution ID")

    execution = await _verify_execution_ownership(db, exec_uuid, user.id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    from app.modules.validation.models import SignedUrlModel

    stmt = delete(SignedUrlModel).where(SignedUrlModel.execution_id == exec_uuid)
    await db.execute(stmt)
    await db.commit()

    return {"status": "revoked"}



# ---------------------------------------------------------------------------
# Validation & Evidence Endpoints (Chunk 13)
# ---------------------------------------------------------------------------
validations_router = APIRouter(prefix="/validations", tags=["validations"])
evidence_router = APIRouter(prefix="/evidence", tags=["evidence"])


@validations_router.get("/{validation_id}/report")
async def get_validation_report(
    validation_id: str,
    request: Request,
    signature: str | None = None,
    format: str | None = None,
    compare_to: str | None = None,
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve full signed, diff-able ValidationReport in HTML or JSON format."""
    try:
        val_uuid = uuid.UUID(validation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid validation report ID")

    from app.modules.validation.models import SignedUrlModel, ValidationReportModel
    from app.modules.validation.schemas import ValidationReport
    from app.modules.executions.reporting import (
        ReportGenerator,
        generate_validation_signature,
        verify_validation_signature,
    )
    from datetime import datetime, timezone

    # 1. Fetch validation report model
    stmt = select(ValidationReportModel).where(ValidationReportModel.id == val_uuid)
    res = await db.execute(stmt)
    report_model = res.scalar_one_or_none()
    if not report_model:
        raise HTTPException(status_code=404, detail="Validation report not found")

    # 2. Check authorization
    if signature:
        try:
            expiry_text, _ = signature.split(".", 1)
            expires_at = int(expiry_text)
        except (ValueError, TypeError):
            raise HTTPException(status_code=401, detail="Invalid signature")

        if expires_at < int(time.time()):
            raise HTTPException(status_code=403, detail="Signed URL has expired")

        if not verify_validation_signature(val_uuid, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Check revocability via signed_urls table
        su_stmt = select(SignedUrlModel).where(
            SignedUrlModel.validation_id == val_uuid,
            SignedUrlModel.signature == signature,
        )
        su_res = await db.execute(su_stmt)
        if not su_res.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Signed URL has been revoked")
    else:
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        proj_repo = ProjectRepository(db)
        project = await proj_repo.get_by_id(report_model.project_id)
        if not project or project.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this project")

    # Fetch project name
    p_stmt = select(Project).where(Project.id == report_model.project_id)
    p_res = await db.execute(p_stmt)
    project_row = p_res.scalar_one_or_none()
    project_name = project_row.name if project_row else "Project"

    # 3. Diff mode
    if compare_to:
        try:
            comp_uuid = uuid.UUID(compare_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid comparison validation ID")

        comp_stmt = select(ValidationReportModel).where(ValidationReportModel.id == comp_uuid)
        comp_res = await db.execute(comp_stmt)
        comp_model = comp_res.scalar_one_or_none()
        if not comp_model:
            raise HTTPException(status_code=404, detail="Comparison validation report not found")

        generator = ReportGenerator(db)
        diff_html = await generator.generate_diff_report(
            validation_id_before=comp_uuid,
            validation_id_after=val_uuid,
            project_name=project_name,
        )
        return HTMLResponse(content=diff_html)

    # 4. JSON Format
    accept_header = request.headers.get("accept", "")
    if format == "json" or (not signature and format != "html" and "application/json" in accept_header and "text/html" not in accept_header):
        vreport = ValidationReport(
            id=report_model.id,
            request=report_model.request,
            impact_report=report_model.impact_report,
            results=report_model.results,
            overall_status=report_model.overall_status,
            duration_ms=report_model.duration_ms,
            started_at=report_model.started_at,
            finished_at=report_model.finished_at,
            evidence_summary=report_model.evidence_summary,
            signed_url=report_model.signed_url,
        )
        return vreport.model_dump(mode="json")

    # 5. HTML Format with persistent signed URL
    base_url = str(request.base_url).rstrip("/")
    sig = generate_validation_signature(val_uuid)
    shareable_url = f"{base_url}/api/v1/validations/{val_uuid}/report?signature={sig}"

    su_check = await db.execute(select(SignedUrlModel).where(SignedUrlModel.signature == sig))
    if not su_check.scalar_one_or_none():
        expiry_ts = int(sig.split(".", 1)[0])
        expires_dt = datetime.fromtimestamp(expiry_ts, tz=timezone.utc)
        db.add(
            SignedUrlModel(
                id=uuid.uuid4(),
                validation_id=val_uuid,
                url=shareable_url,
                signature=sig,
                expires_at=expires_dt,
                created_by=user.id if user else None,
            )
        )
        if not report_model.signed_url:
            report_model.signed_url = shareable_url
        await db.commit()

    generator = ReportGenerator(db)
    html_content = await generator.generate_validation_report(val_uuid, project_name=project_name)
    return HTMLResponse(content=html_content)


@evidence_router.get("/{evidence_id}/dom")
async def get_evidence_dom(
    evidence_id: str,
    db: AsyncSession = Depends(get_session),
):
    """Serve full DOM snapshot on-demand without bloating main report payloads."""
    try:
        eid = uuid.UUID(evidence_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid evidence ID")

    from app.modules.executions.evidence_model import Evidence

    stmt = select(Evidence).where(Evidence.id == eid)
    res = await db.execute(stmt)
    evidence = res.scalar_one_or_none()
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    dom = evidence.dom_snapshot or "<html><body><p>No DOM snapshot recorded.</p></body></html>"
    return HTMLResponse(content=dom)


