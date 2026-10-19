"""Flow API endpoints.

Handles flow CRUD and execution creation.
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.api import get_current_user, get_session
from app.modules.executions.schemas import ExecutionCreate, ExecutionRead
from app.modules.executions.service import ExecutionService
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

# Per-user concurrency guard. Requests over capacity are rejected explicitly;
# they must not create executions that can remain CREATED indefinitely.
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


from app.modules.auth.rbac import verify_project_role
from app.modules.auth.token_scopes import (
    SCOPE_EXECUTIONS_WRITE,
    SCOPE_FLOWS_READ,
    SCOPE_FLOWS_WRITE,
    require_scope,
)


async def _verify_project_ownership(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID, min_role: str = "viewer"
):
    """Verify a project exists and user has at least min_role."""
    from app.modules.users.models import User
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return await verify_project_role(db, project_id, user, min_role=min_role)


async def _verify_flow_ownership(
    db: AsyncSession, flow_id: uuid.UUID, user_id: uuid.UUID, min_role: str = "viewer"
):
    """Verify a flow exists and user has at least min_role via project role."""
    from app.modules.flows.repository import FlowRepository
    from app.modules.users.models import User
    flow_repo = FlowRepository(db)
    flow = await flow_repo.get_by_id(flow_id)
    if flow is None:
        return None
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    await verify_project_role(db, flow.project_id, user, min_role=min_role)
    return flow


@router.post("/", response_model=FlowRead, status_code=201)
async def create_flow(
    data: FlowCreate,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    """Create a new flow."""
    await _verify_project_ownership(db, data.project_id, user.id, min_role="admin")

    service = FlowService(db)
    return await service.create_flow(data)


@router.get("/", response_model=list[FlowRead])
async def list_flows(
    project_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(require_scope(SCOPE_FLOWS_READ)),
    db: AsyncSession = Depends(get_session),
):
    """List flows for a project."""
    await _verify_project_ownership(db, project_id, user.id, min_role="viewer")

    service = FlowService(db)
    return await service.list_flows(project_id, skip=skip, limit=limit)


@router.get("/{flow_id}", response_model=FlowRead)
async def get_flow(
    flow_id: str,
    user: User = Depends(require_scope(SCOPE_FLOWS_READ)),
    db: AsyncSession = Depends(get_session),
):
    """Get flow by ID."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id, min_role="viewer")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    return flow


@router.put("/{flow_id}", response_model=FlowRead)
async def update_flow(
    flow_id: str,
    data: FlowUpdate,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    """Update a flow."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id, min_role="admin")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    service = FlowService(db)
    return await service.update_flow(uuid.UUID(flow_id), data)


@router.delete("/{flow_id}", status_code=204)
async def delete_flow(
    flow_id: str,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    """Delete a flow."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id, min_role="admin")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    service = FlowService(db)
    await service.delete_flow(uuid.UUID(flow_id))


@router.post("/{flow_id}/executions", response_model=ExecutionRead, status_code=201)
async def create_flow_execution(
    flow_id: str,
    response: Response,
    user: User = Depends(require_scope(SCOPE_EXECUTIONS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    """Create and enqueue an execution for a flow."""
    try:
        flow = await _verify_flow_ownership(db, uuid.UUID(flow_id), user.id, min_role="tester")
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid flow ID")
    if flow is None:
        raise HTTPException(status_code=404, detail="Flow not found")

    from sqlalchemy import select
    from app.modules.executions.models import Execution, ExecutionStatus
    from app.modules.flows.repository import FlowRepository

    if flow.repeatability == "non_repeatable":
        # Serialize concurrent run requests on the flow row so a single-use
        # operation cannot be accepted twice before either execution commits.
        locked = await db.execute(
            select(Flow).where(Flow.id == flow.id).with_for_update()
        )
        flow = locked.scalar_one()
        previous = await db.execute(
            select(Execution.id).where(
                Execution.flow_id == flow.id,
                Execution.status.in_([
                    ExecutionStatus.COMPLETED, ExecutionStatus.FAILED,
                    ExecutionStatus.CANCELLED, ExecutionStatus.TIMEOUT,
                    ExecutionStatus.BLOCKED, ExecutionStatus.UNVERIFIED,
                ]),
            ).limit(1)
        )
        if previous.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail={
                "code": "FLOW_NOT_REPEATABLE",
                "message": "This flow has already run and requires an explicit reset before it can run again.",
                "reset_strategy": flow.reset_strategy,
            })

    project_flows = await FlowRepository(db).list_by_project(flow.project_id)
    from app.modules.flows.dependency_resolver import DependencyResolutionError, resolve_dependency_plan
    try:
        dependency_plan = resolve_dependency_plan(flow, project_flows)
    except DependencyResolutionError as exc:
        raise HTTPException(status_code=409, detail={
            "code": exc.code, "message": str(exc), "path": exc.path,
        }) from exc

    # Enforce an explicit capacity response before creating a durable record.
    active = await _count_active_executions(db, user.id)
    if active >= MAX_ACTIVE_EXECUTIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"Execution capacity reached ({MAX_ACTIVE_EXECUTIONS_PER_USER} active runs). Retry later.",
        )

    # Create execution
    exec_service = ExecutionService(db)
    project = await ProjectRepository(db).get_by_id(flow.project_id)
    snapshot = {
        "version": flow.version,
        "name": flow.name,
        "objective": flow.objective,
        "steps": flow.steps,
        "success_condition": flow.success_condition,
        "preconditions": flow.preconditions,
        "dependencies": flow.dependencies or [],
        "dependency_plan": dependency_plan,
        "repeatability": flow.repeatability,
        "reset_strategy": flow.reset_strategy,
        "target_url": project.base_url if project else "",
    }
    execution = await exec_service.create_execution(
        ExecutionCreate(flow_id=uuid.UUID(flow_id)),
        flow_version=flow.version,
        flow_snapshot=snapshot,
    )
    await db.commit()

    # Dispatch after the response body is sent — keep browser work off the hot path.
    response.background = BackgroundTask(_schedule_dispatch, str(execution.id))
    return execution


@router.post("/{flow_id}/visual-reference", status_code=201)
async def upload_visual_reference(
    flow_id: uuid.UUID,
    file: UploadFile | None = None,
    screenshot_url: str | None = Form(None),
    label: str = Form("Baseline"),
    a11y_tree: str | None = Form(None),
    viewport: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Upload a baseline screenshot and metadata for visual validation of this flow."""
    import base64
    import json
    from app.modules.validation.models import VisualReferenceModel

    flow = await FlowService(db).get_flow(flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    project = await ProjectRepository(db).get_by_id(flow.project_id)
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this flow")

    final_screenshot_url = screenshot_url
    if file:
        content = await file.read()
        b64 = base64.b64encode(content).decode()
        mime = file.content_type or "image/png"
        final_screenshot_url = f"data:{mime};base64,{b64}"

    if not final_screenshot_url:
        raise HTTPException(status_code=422, detail="Either file or screenshot_url must be provided")

    parsed_a11y = {}
    if a11y_tree:
        try:
            parsed_a11y = json.loads(a11y_tree)
        except Exception:
            parsed_a11y = {}

    parsed_viewport = {"width": 1280, "height": 720}
    if viewport:
        try:
            parsed_viewport = json.loads(viewport)
        except Exception:
            parsed_viewport = {"width": 1280, "height": 720}

    ref = VisualReferenceModel(
        flow_id=flow_id,
        screenshot_url=final_screenshot_url,
        a11y_tree=parsed_a11y,
        viewport=parsed_viewport,
        label=label,
    )
    db.add(ref)
    await db.commit()
    await db.refresh(ref)

    return {
        "id": str(ref.id),
        "flow_id": str(ref.flow_id),
        "label": ref.label,
        "screenshot_url": ref.screenshot_url if not ref.screenshot_url.startswith("data:") else "[data_uri]",
        "created_at": ref.created_at.isoformat(),
    }

