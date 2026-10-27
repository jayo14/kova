import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.auth.rbac import verify_project_role
from app.modules.auth.token_scopes import SCOPE_FLOWS_WRITE, require_scope
from app.modules.suites.models import SuiteRun, TestSuite
from app.modules.suites.schemas import (
    FlakinessRead,
    SuiteCreate,
    SuiteDetail,
    SuiteRead,
    SuiteRunDetail,
    SuiteRunRead,
    SuiteRunRequest,
    SuiteUpdate,
)
from app.modules.suites.service import SuiteService
from app.modules.users.models import User

suites_router = APIRouter(prefix="/suites", tags=["suites"])
suite_runs_router = APIRouter(prefix="/suite-runs", tags=["suites"])


def _uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid {label}")


async def _get_suite(
    db: AsyncSession,
    suite_id: uuid.UUID,
    user: User,
    min_role: str = "viewer",
) -> TestSuite:
    service = SuiteService(db)
    suite = await service.get_suite(suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    await verify_project_role(db, suite.project_id, user, min_role=min_role)
    return suite


async def _get_run(db: AsyncSession, run_id: uuid.UUID, user: User) -> SuiteRun:
    service = SuiteService(db)
    run = await service.repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Suite run not found")
    await verify_project_role(db, run.project_id, user, min_role="viewer")
    return run


@suites_router.post("/", response_model=SuiteRead, status_code=201)
async def create_suite(
    data: SuiteCreate,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    await verify_project_role(db, data.project_id, user, min_role="tester")
    service = SuiteService(db)
    try:
        return await service.create_suite(data, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@suites_router.get("/", response_model=list[SuiteRead])
async def list_suites(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    project_uuid = _uuid(project_id, "project ID")
    await verify_project_role(db, project_uuid, user, min_role="viewer")
    service = SuiteService(db)
    return await service.list_suites(project_uuid)


@suites_router.get("/{suite_id}", response_model=SuiteDetail)
async def get_suite(
    suite_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    suite = await _get_suite(db, _uuid(suite_id, "suite ID"), user)
    service = SuiteService(db)
    return await service.suite_detail(suite)


@suites_router.patch("/{suite_id}", response_model=SuiteRead)
async def update_suite(
    suite_id: str,
    data: SuiteUpdate,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    suite = await _get_suite(db, _uuid(suite_id, "suite ID"), user, min_role="tester")
    service = SuiteService(db)
    try:
        return await service.update_suite(suite, data, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@suites_router.delete("/{suite_id}", status_code=204)
async def delete_suite(
    suite_id: str,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    suite = await _get_suite(db, _uuid(suite_id, "suite ID"), user, min_role="admin")
    service = SuiteService(db)
    await service.delete_suite(suite)
    return None


@suites_router.post("/{suite_id}/runs", response_model=SuiteRunDetail, status_code=201)
async def run_suite(
    suite_id: str,
    data: SuiteRunRequest,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    suite = await _get_suite(db, _uuid(suite_id, "suite ID"), user, min_role="tester")
    service = SuiteService(db)
    try:
        run = await service.run_suite(suite, data, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await service.get_run_with_items(run)


@suites_router.get("/{suite_id}/runs", response_model=list[SuiteRunRead])
async def list_suite_runs(
    suite_id: str,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    suite = await _get_suite(db, _uuid(suite_id, "suite ID"), user)
    service = SuiteService(db)
    limit = max(1, min(limit, 200))
    return await service.repo.list_runs(suite.id, limit=limit)


@suites_router.get("/{suite_id}/flakiness", response_model=FlakinessRead)
async def suite_flakiness(
    suite_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    suite = await _get_suite(db, _uuid(suite_id, "suite ID"), user)
    service = SuiteService(db)
    return await service.flakiness(suite.id)


@suite_runs_router.get("/{run_id}", response_model=SuiteRunDetail)
async def get_suite_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    run = await _get_run(db, _uuid(run_id, "suite run ID"), user)
    service = SuiteService(db)
    return await service.get_run_with_items(run)
