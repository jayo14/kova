"""Flow API endpoints.

Handles flow CRUD and execution creation.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.executions.schemas import ExecutionRead
from app.modules.flows.models import Flow
from app.modules.flows.schemas import FlowCreate, FlowRead, FlowUpdate
from app.modules.flows.service import FlowService
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User

router = APIRouter(prefix="/flows", tags=["flows"])

logger = logging.getLogger(__name__)

# Strong refs so fire-and-forget dispatch tasks are not GC'd mid-run
_dispatch_tasks: set[asyncio.Task] = set()

# Concurrency safety (§28): a user may not pile up unbounded concurrent
# Chromium sessions. Above this many non-terminal executions per user, new
# executions stay CREATED (queued by omission) until running ones finish.
MAX_ACTIVE_EXECUTIONS_PER_USER = 5


async def _count_active_executions(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Count the user's non-terminal executions (CREATED..RUNNING/PAUSED etc)."""
    from sqlalchemy import select, func as sa_func
    from app.modules.executions.models import Execution, ExecutionStatus

    non_terminal = [
        s.value for s in ExecutionStatus
        if s not in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT,
            ExecutionStatus.BLOCKED,
            ExecutionStatus.UNVERIFIED,
        )
    ]
    result = await db.execute(
        select(sa_func.count(Execution.id))
        .select_from(Execution)
        .join(Flow, Execution.flow_id == Flow.id)
        .join(Project, Flow.project_id == Project.id)
        .where(Project.user_id == user_id, Execution.status.in_(non_terminal))
    )
    return int(result.scalar_one() or 0)


async def _dispatch_execution(execution_id: str) -> None:
    """Queue on Celery when a worker is online; else run via asyncio.

    Runs only after the HTTP response is sent (BackgroundTask → create_task).
    """
    try:
        from app.workers.celery_app import celery_app
        from app.workers.tasks.executions import run_execution

        def _ping():
            inspector = celery_app.control.inspect(timeout=0.2)
            return inspector.ping() if inspector else None

        active_workers = await asyncio.to_thread(_ping)
        if active_workers:
            await asyncio.to_thread(run_execution.delay, execution_id)
            logger.info(
                "Dispatched execution %s to Celery worker: %s",
                execution_id,
                list(active_workers.keys()),
            )
            return
    except Exception as celery_err:
        logger.warning("Celery inspector error for execution %s: %s", execution_id, celery_err)

    logger.info(
        "No active Celery worker online; executing %s via background asyncio task",
        execution_id,
    )
    from app.workers.tasks.executions import _run_execution_async

    await _run_execution_async(None, execution_id)


async def _schedule_dispatch(execution_id: str) -> None:
    """Create the dispatch task without awaiting it (keeps API response free)."""
    task = asyncio.create_task(_dispatch_execution(execution_id))
    _dispatch_tasks.add(task)
    task.add_done_callback(_dispatch_tasks.discard)


async def _verify_project_ownership(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
):
    """Verify a project exists and belongs to the user."""
    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id_and_user(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _verify_flow_ownership(
    db: AsyncSession, flow_id: uuid.UUID, user_id: uuid.UUID
):
    """Verify a flow exists and belongs to the user via project ownership."""
    from app.modules.flows.repository import FlowRepository
    flow_repo = FlowRepository(db)
    flow = await flow_repo.get_by_id(flow_id)
    if flow is None:
        return None
    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id_and_user(flow.project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.post("/", response_model=FlowRead, status_code=201)
async def create_flow(
    data: FlowCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a new flow."""
    await _verify_project_ownership(db, data.project_id, user.id)

    service = FlowService(db)
    return await service.create_flow(data)


@router.get("/", response_model=list[FlowRead])
async def list_flows(
    project_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List flows for a project."""
    await _verify_project_ownership(db, project_id, user.id)

    service = FlowService(db)
    return await service.list_flows(project_id, skip=skip, limit=limit)


@router.get("/{flow_id}", response_model=FlowRead)
async def get_flow(
    flow_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get flow by ID."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.put("/{flow_id}", response_model=FlowRead)
async def update_flow(
    flow_id: str,
    data: FlowUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Update a flow."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    service = FlowService(db)
    return await service.update_flow(uuid.UUID(flow_id), data)


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(
    flow_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Delete a flow."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    service = FlowService(db)
    await service.delete_flow(uuid.UUID(flow_id))


@router.post("/{flow_id}/executions", response_model=ExecutionRead, status_code=201)
async def create_flow_execution(
    flow_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create and enqueue an execution for a flow.

    This is the main endpoint to trigger flow execution.
    1. Creates execution record
    2. Schedules Celery/asyncio dispatch after the response is sent
    3. Returns execution (API never waits on browser or broker inspect)
    """
    from app.modules.executions.service import ExecutionService

    # Validate flow exists and user owns it
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    # Concurrency guard: leave the execution CREATED (queued) instead of
    # launching another Chromium when the user already has too many active runs.
    active = await _count_active_executions(db, user.id)
    dispatch = active < MAX_ACTIVE_EXECUTIONS_PER_USER
    if not dispatch:
        logger.info(
            "Execution for user %s stays queued: %d active runs (limit %d)",
            user.id, active, MAX_ACTIVE_EXECUTIONS_PER_USER,
        )

    # Create execution
    exec_service = ExecutionService(db)
    execution = await exec_service.create_execution(
        __import__("app.modules.executions.schemas", fromlist=["ExecutionCreate"]).ExecutionCreate(
            flow_id=uuid.UUID(flow_id)
        )
    )
    await db.commit()

    if dispatch:
        # Dispatch after the response body is sent — keep enqueue off the hot path.
        # Must go through the BackgroundTasks dependency: FastAPI discards
        # response.background when the endpoint returns a model, so setting
        # response.background here would silently drop the dispatch.
        background_tasks.add_task(_schedule_dispatch, str(execution.id))
    return execution
