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
    flow_ids: list[uuid.UUID] | None = None
    base_url: str | None = None
    fail_on_healed: bool = False
    diff_content: str | None = None
    changed_files: list[str] | None = None
    commit_message: str | None = None
    persona: str | None = None
    timeout_seconds: int = 1800


class CIRunExecutionSummary(BaseModel):
    id: uuid.UUID
    flow_id: uuid.UUID
    status: str


class CIRunResponse(BaseModel):
    project_id: uuid.UUID
    executions: list[CIRunExecutionSummary]
    count: int


from app.modules.validation.runner import ValidationRunner
from app.modules.validation.schemas import (
    ValidationCreate,
    ValidationReport,
    ValidationRequest,
    ValidationRunRead,
)
from app.modules.validation.service import ValidationService


from app.modules.auth.rbac import verify_project_role
from app.modules.auth.token_scopes import SCOPE_CI_VALIDATE, require_scope
from app.modules.organizations.service import OrganizationService


@router.post("/run", status_code=status.HTTP_201_CREATED)
async def ci_run(
    data: CIRunRequest,
    response: Response,
    user: User = Depends(require_scope(SCOPE_CI_VALIDATE)),
    db: AsyncSession = Depends(get_session),
):
    """Trigger CI execution for specified flows (legacy) or minimal valid path from git diff."""
    # 1. Verify project access with tester role
    project = await verify_project_role(db, data.project_id, user, min_role="tester")

    if project.org_id:
        from app.modules.billing.service import BillingService
        billing_service = BillingService(db)
        await billing_service.check_execution_limit(project.org_id)
        org_service = OrganizationService(db)
        await org_service.check_execution_quota(project.org_id)

    if data.base_url:
        project.base_url = data.base_url

    # Branch A: Legacy flow_ids execution
    if data.flow_ids:
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

        response.status_code = status.HTTP_201_CREATED
        return CIRunResponse(
            project_id=project.id,
            executions=executions,
            count=len(executions),
        )

    # Branch B: Targeted diff execution
    if data.diff_content or data.changed_files:
        runner = ValidationRunner(db)
        req = ValidationRequest(
            project_id=data.project_id,
            base_url=data.base_url,
            diff_content=data.diff_content,
            changed_files=data.changed_files,
            commit_message=data.commit_message,
            persona=data.persona,
            timeout_seconds=data.timeout_seconds,
        )
        report = await runner.run(req)
        response.status_code = status.HTTP_200_OK
        return report

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Must provide either flow_ids or diff_content/changed_files",
    )


@router.post("/validate")
async def ci_validate(
    data: dict,
    response: Response,
    user: User = Depends(require_scope(SCOPE_CI_VALIDATE)),
    db: AsyncSession = Depends(get_session),
):
    """Trigger an explainable continuous validation run (async run or synchronous targeted report)."""
    # Verify project ownership and tester role
    project_id_raw = data.get("project_id")
    if not project_id_raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id is required")
    try:
        project_uuid = uuid.UUID(str(project_id_raw))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project_id UUID")

    project = await verify_project_role(db, project_uuid, user, min_role="tester")

    if project.org_id:
        from app.modules.billing.service import BillingService
        billing_service = BillingService(db)
        await billing_service.check_execution_limit(project.org_id)
        org_service = OrganizationService(db)
        await org_service.check_execution_quota(project.org_id)

    # If request has scope, route to asynchronous ValidationRun (continuous validation baseline)
    if "scope" in data:
        vcreate = ValidationCreate.model_validate(data)
        service = ValidationService(db)
        vrun = await service.create_validation_run(vcreate)
        await db.commit()
        await db.refresh(vrun)
        response.status_code = status.HTTP_201_CREATED
        return ValidationRunRead.model_validate(vrun)

    # Otherwise route to synchronous targeted regression runner
    vreq = ValidationRequest.model_validate(data)
    runner = ValidationRunner(db)
    report = await runner.run(vreq)
    response.status_code = status.HTTP_200_OK
    return report


@router.get("/validate/{validation_run_id}", response_model=ValidationRunRead)
async def get_ci_validation(
    validation_run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Poll the status, baseline diff, and exit code of a continuous validation run."""
    service = ValidationService(db)
    vrun = await service.evaluate_validation_run(validation_run_id)
    if not vrun:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation run not found")

    # Verify project access
    await verify_project_role(db, vrun.project_id, user, min_role="viewer")

    await db.commit()
    await db.refresh(vrun)
    return vrun


@router.get("/validate/{validation_run_id}/report")
async def get_ci_validation_report(
    validation_run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve full traceable validation report with impact reasons, baseline comparisons, and execution breakdown."""
    service = ValidationService(db)
    vrun = await service.evaluate_validation_run(validation_run_id)
    if not vrun:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation run not found")

    # Verify project access
    project = await verify_project_role(db, vrun.project_id, user, min_role="viewer")

    await db.commit()
    await db.refresh(vrun)

    return {
        "validation_run_id": str(vrun.id),
        "project_id": str(vrun.project_id),
        "project_name": project.name,
        "commit_sha": vrun.commit_sha,
        "branch": vrun.branch,
        "scope": vrun.scope,
        "status": vrun.status,
        "exit_code": vrun.exit_code,
        "summary": vrun.summary,
        "impact_report": vrun.impact_report,
        "baseline_diff": vrun.baseline_diff,
        "selected_flow_ids": vrun.selected_flow_ids,
        "execution_ids": vrun.execution_ids,
        "created_at": vrun.created_at.isoformat() if vrun.created_at else None,
        "completed_at": vrun.completed_at.isoformat() if vrun.completed_at else None,
    }
