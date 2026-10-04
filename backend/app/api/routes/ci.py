import asyncio
import logging
import uuid
from typing import Set

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.executions.service import ExecutionService
from app.modules.executions.schemas import ExecutionCreate
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User

router = APIRouter(prefix="/ci", tags=["ci"])
logger = logging.getLogger(__name__)

_ci_dispatch_tasks: Set[asyncio.Task] = set()


async def _dispatch_execution(execution_id: str) -> None:
    try:
        from app.workers.tasks.executions import _run_execution_async
        await _run_execution_async(None, execution_id)
    except Exception as e:
        logger.error("Failed to dispatch CI execution %s: %s", execution_id, e)


def _schedule_dispatch(execution_id: str) -> None:
    task = asyncio.create_task(_dispatch_execution(execution_id))
    _ci_dispatch_tasks.add(task)
    task.add_done_callback(_ci_dispatch_tasks.discard)


class CIRunRequest(BaseModel):
    project_id: uuid.UUID
    flow_ids: list[uuid.UUID]
    base_url: str | None = None
    fail_on_healed: bool = False


class CIRunExecutionSummary(BaseModel):
    id: uuid.UUID
    flow_id: uuid.UUID
    status: str


class CIRunResponse(BaseModel):
    project_id: uuid.UUID
    executions: list[CIRunExecutionSummary]
    count: int


@router.post("/run", response_model=CIRunResponse, status_code=status.HTTP_201_CREATED)
async def ci_run(
    data: CIRunRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Trigger CI execution for specified flows in a project."""
    # 1. Verify project belongs to user
    stmt = select(Project).where(Project.id == data.project_id, Project.user_id == user.id)
    project_res = await db.execute(stmt)
    project = project_res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or not owned by user",
        )

    if data.base_url:
        project.base_url = data.base_url

    # 2. Verify all flow_ids belong to this project and create executions
    exec_service = ExecutionService(db)
    executions: list[CIRunExecutionSummary] = []
    execution_ids_to_dispatch: list[str] = []

    for flow_id in data.flow_ids:
        flow_stmt = select(Flow).where(Flow.id == flow_id, Flow.project_id == project.id)
        flow_res = await db.execute(flow_stmt)
        flow = flow_res.scalar_one_or_none()
        if not flow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Flow {flow_id} not found in project {project.id}",
            )

        execution = await exec_service.create_execution(ExecutionCreate(flow_id=flow.id))
        executions.append(
            CIRunExecutionSummary(
                id=execution.id,
                flow_id=flow.id,
                status=execution.status.value if hasattr(execution.status, "value") else str(execution.status),
            )
        )
        execution_ids_to_dispatch.append(str(execution.id))

    await db.commit()

    if data.fail_on_healed:
        from app.engine.execution.control import set_execution_fail_on_healed
        for eid in execution_ids_to_dispatch:
            await set_execution_fail_on_healed(eid, True)

    # Schedule execution dispatches in background
    for eid in execution_ids_to_dispatch:
        _schedule_dispatch(eid)

    return CIRunResponse(
        project_id=project.id,
        executions=executions,
        count=len(executions),
    )
