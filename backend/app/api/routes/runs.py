"""Run orchestration and multi-journey execution management routes.

Provides first-class run orchestration with bounded concurrency, isolated
browser sessions, persistent run-level progress tracking, SSE status streams,
and unified cancellation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from app.api import get_current_user, get_session
from app.infrastructure.database.session import async_session_factory
from app.modules.users.models import User
from app.modules.executions.models import ExecutionStatus
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.service import ExecutionService
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.validation.models import ValidationRun, ValidationStatus
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

# Hold strong references to active background orchestrator tasks so they aren't GC'd
_orchestrator_tasks: set[asyncio.Task] = set()


class RunCreateRequest(BaseModel):
    project_id: uuid.UUID
    execution_ids: list[str] = Field(..., min_length=1)
    concurrency_limit: int = Field(default=2, ge=1, le=5)
    parallel: bool = True


class RunExecutionItem(BaseModel):
    id: str
    flow_id: str | None = None
    mission_name: str | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    step_progress: str | None = None


class RunResponse(BaseModel):
    id: str
    project_id: str
    status: str
    summary: dict[str, Any]
    execution_ids: list[str]
    created_at: str | None = None
    completed_at: str | None = None


class RunDetailResponse(BaseModel):
    id: str
    project_id: str
    status: str
    summary: dict[str, Any]
    progress: int
    created_at: str | None = None
    completed_at: str | None = None
    executions: list[RunExecutionItem]


async def _verify_project_access(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> Project:
    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _orchestrate_run(
    run_id: uuid.UUID,
    execution_ids: list[str],
    concurrency_limit: int,
    parallel: bool,
) -> None:
    """Execute run executions with strictly bounded concurrency and isolated browser sandboxes."""
    from app.api.dispatch import dispatch_execution

    limit = concurrency_limit if parallel else 1
    semaphore = asyncio.Semaphore(limit)

    async def _execute_with_bound(exec_id: str):
        async with semaphore:
            try:
                # Check if the run has already been cancelled before starting this execution
                async with async_session_factory() as check_db:
                    res = await check_db.execute(select(ValidationRun.status).where(ValidationRun.id == run_id))
                    current_status = res.scalar_one_or_none()
                    if current_status == "CANCELLED":
                        logger.info("Run %s cancelled, skipping execution %s", run_id, exec_id)
                        return

                await dispatch_execution(exec_id, context="run_orchestrator")
            except Exception as e:
                logger.error("Error executing %s in run %s: %s", exec_id, run_id, e)

    workers = [asyncio.create_task(_execute_with_bound(eid)) for eid in execution_ids]
    await asyncio.gather(*workers, return_exceptions=True)

    # Reconcile final status of the run
    try:
        async with async_session_factory() as fin_db:
            res = await fin_db.execute(select(ValidationRun).where(ValidationRun.id == run_id))
            run = res.scalar_one_or_none()
            if run and run.status == "RUNNING":
                exec_repo = ExecutionRepository(fin_db)
                passed_cnt = 0
                failed_cnt = 0
                for eid in execution_ids:
                    try:
                        ex = await exec_repo.get_by_id(uuid.UUID(eid))
                        if ex:
                            if ex.status == ExecutionStatus.COMPLETED.value:
                                passed_cnt += 1
                            elif ex.status in (
                                ExecutionStatus.FAILED.value,
                                ExecutionStatus.ERROR.value,
                                ExecutionStatus.TIMEOUT.value,
                                ExecutionStatus.BLOCKED.value,
                            ):
                                failed_cnt += 1
                    except Exception:
                        pass

                all_passed = passed_cnt == len(execution_ids) and failed_cnt == 0
                run.status = ValidationStatus.PASSED.value if all_passed else ValidationStatus.FAILED.value
                run.completed_at = datetime.now(UTC)
                run.summary = {
                    "total": len(execution_ids),
                    "passed": passed_cnt,
                    "failed": failed_cnt,
                    "running": 0,
                    "queued": 0,
                }
                await fin_db.commit()
    except Exception as fin_err:
        logger.error("Failed to finalize run %s: %s", run_id, fin_err)


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    data: RunCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a new unified validation run with bounded concurrency."""
    project = await _verify_project_access(db, data.project_id, user.id)

    # Verify all executions exist and belong to this project
    exec_repo = ExecutionRepository(db)
    flow_ids: list[str] = []
    for exec_id_str in data.execution_ids:
        try:
            exec_uuid = uuid.UUID(exec_id_str)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid execution ID: {exec_id_str}")

        execution = await exec_repo.get_by_id(exec_uuid)
        if not execution:
            raise HTTPException(status_code=404, detail=f"Execution not found: {exec_id_str}")

        flow_res = await db.execute(select(Flow).where(Flow.id == execution.flow_id))
        flow = flow_res.scalar_one_or_none()
        if not flow or flow.project_id != project.id:
            raise HTTPException(
                status_code=403,
                detail=f"Execution {exec_id_str} does not belong to project {project.id}",
            )
        flow_ids.append(str(flow.id))

    initial_summary = {
        "total": len(data.execution_ids),
        "queued": len(data.execution_ids),
        "running": 0,
        "passed": 0,
        "failed": 0,
        "blocked": 0,
    }

    run_id = uuid.uuid4()
    run = ValidationRun(
        id=run_id,
        project_id=project.id,
        base_url=project.base_url,
        status="RUNNING",
        execution_ids=data.execution_ids,
        selected_flow_ids=flow_ids,
        summary=initial_summary,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Schedule bounded background execution
    orchestrator_task = asyncio.create_task(
        _orchestrate_run(
            run_id=run.id,
            execution_ids=data.execution_ids,
            concurrency_limit=data.concurrency_limit,
            parallel=data.parallel,
        )
    )
    _orchestrator_tasks.add(orchestrator_task)
    orchestrator_task.add_done_callback(_orchestrator_tasks.discard)

    return RunResponse(
        id=str(run.id),
        project_id=str(run.project_id),
        status=run.status,
        summary=run.summary or initial_summary,
        execution_ids=run.execution_ids or [],
        created_at=run.created_at.isoformat() if run.created_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get authoritative run state, counters, step progress, and execution items."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid run ID")

    run_stmt = select(ValidationRun).where(ValidationRun.id == run_uuid)
    run_res = await db.execute(run_stmt)
    run = run_res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    await _verify_project_access(db, run.project_id, user.id)

    # Fetch execution details for each execution in the run
    exec_repo = ExecutionRepository(db)
    items: list[RunExecutionItem] = []
    queued_cnt = 0
    running_cnt = 0
    passed_cnt = 0
    failed_cnt = 0
    blocked_cnt = 0

    for eid_str in run.execution_ids or []:
        try:
            ex = await exec_repo.get_by_id(uuid.UUID(eid_str))
            if not ex:
                continue

            # Load flow name
            flow_name = None
            if ex.flow_id:
                flow_res = await db.execute(select(Flow.name).where(Flow.id == ex.flow_id))
                flow_name = flow_res.scalar_one_or_none()

            st = ex.status
            if st in (ExecutionStatus.COMPLETED.value, "PASSED"):
                passed_cnt += 1
            elif st in (
                ExecutionStatus.FAILED.value,
                ExecutionStatus.ERROR.value,
                ExecutionStatus.TIMEOUT.value,
            ):
                failed_cnt += 1
            elif st == ExecutionStatus.BLOCKED.value:
                blocked_cnt += 1
            elif st in (
                ExecutionStatus.RUNNING.value,
                ExecutionStatus.INITIALIZING.value,
                ExecutionStatus.BROWSER_READY.value,
                ExecutionStatus.PLANNING.value,
            ):
                running_cnt += 1
            else:
                queued_cnt += 1

            duration_ms = None
            if ex.started_at and ex.completed_at:
                duration_ms = int((ex.completed_at - ex.started_at).total_seconds() * 1000)

            items.append(
                RunExecutionItem(
                    id=str(ex.id),
                    flow_id=str(ex.flow_id) if ex.flow_id else None,
                    mission_name=flow_name or (ex.flow_snapshot.get("name") if ex.flow_snapshot else None) or "User Journey",
                    status=ex.status,
                    error_code=ex.error_code,
                    error_message=ex.error_message,
                    created_at=ex.created_at.isoformat() if ex.created_at else None,
                    completed_at=ex.completed_at.isoformat() if ex.completed_at else None,
                    duration_ms=duration_ms,
                )
            )
        except Exception as ex_err:
            logger.warning("Failed to fetch execution %s: %s", eid_str, ex_err)

    total = len(run.execution_ids or [])
    completed_terminal = passed_cnt + failed_cnt + blocked_cnt
    progress = int(completed_terminal / total * 100) if total > 0 else 0

    summary = {
        "total": total,
        "queued": queued_cnt,
        "running": running_cnt,
        "passed": passed_cnt,
        "failed": failed_cnt,
        "blocked": blocked_cnt,
    }

    # If run was RUNNING and all executions have settled, update the DB record
    if run.status == "RUNNING" and completed_terminal >= total > 0:
        all_passed = passed_cnt == total and failed_cnt == 0
        run.status = ValidationStatus.PASSED.value if all_passed else ValidationStatus.FAILED.value
        run.completed_at = datetime.now(UTC)
        run.summary = summary
        await db.commit()

    return RunDetailResponse(
        id=str(run.id),
        project_id=str(run.project_id),
        status=run.status,
        summary=summary,
        progress=progress,
        created_at=run.created_at.isoformat() if run.created_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        executions=items,
    )


@router.get("/{run_id}/events/stream")
async def stream_run_events(
    run_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Server-Sent Events (SSE) live stream for run progress and execution status changes."""
    try:
        run_uuid = uuid.UUID(run_id)
        async with async_session_factory() as auth_db:
            run_stmt = select(ValidationRun).where(ValidationRun.id == run_uuid)
            run_res = await auth_db.execute(run_stmt)
            run = run_res.scalar_one_or_none()
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            await _verify_project_access(auth_db, run.project_id, user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid run ID")

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield ": connected\n\n"

            last_summary_snapshot: str = ""

            while True:
                if await request.is_disconnected():
                    break

                async with async_session_factory() as poll_db:
                    res = await poll_db.execute(select(ValidationRun).where(ValidationRun.id == run_uuid))
                    cur_run = res.scalar_one_or_none()
                    if not cur_run:
                        break

                    exec_repo = ExecutionRepository(poll_db)
                    items_data: list[dict] = []
                    passed_cnt = 0
                    failed_cnt = 0
                    running_cnt = 0
                    queued_cnt = 0
                    blocked_cnt = 0

                    for eid_str in cur_run.execution_ids or []:
                        try:
                            ex = await exec_repo.get_by_id(uuid.UUID(eid_str))
                            if not ex:
                                continue
                            st = ex.status
                            if st in (ExecutionStatus.COMPLETED.value, "PASSED"):
                                passed_cnt += 1
                            elif st in (
                                ExecutionStatus.FAILED.value,
                                ExecutionStatus.ERROR.value,
                                ExecutionStatus.TIMEOUT.value,
                            ):
                                failed_cnt += 1
                            elif st == ExecutionStatus.BLOCKED.value:
                                blocked_cnt += 1
                            elif st in (
                                ExecutionStatus.RUNNING.value,
                                ExecutionStatus.INITIALIZING.value,
                                ExecutionStatus.BROWSER_READY.value,
                                ExecutionStatus.PLANNING.value,
                            ):
                                running_cnt += 1
                            else:
                                queued_cnt += 1

                            items_data.append({
                                "id": str(ex.id),
                                "status": ex.status,
                                "error_code": ex.error_code,
                                "error_message": ex.error_message,
                            })
                        except Exception:
                            pass

                    total = len(cur_run.execution_ids or [])
                    completed = passed_cnt + failed_cnt + blocked_cnt
                    progress = int(completed / total * 100) if total > 0 else 0

                    current_snapshot = json.dumps({
                        "run_id": str(cur_run.id),
                        "status": cur_run.status,
                        "progress": progress,
                        "summary": {
                            "total": total,
                            "queued": queued_cnt,
                            "running": running_cnt,
                            "passed": passed_cnt,
                            "failed": failed_cnt,
                            "blocked": blocked_cnt,
                        },
                        "executions": items_data,
                    })

                    if current_snapshot != last_summary_snapshot:
                        last_summary_snapshot = current_snapshot
                        yield f"event: run_update\ndata: {current_snapshot}\n\n"

                    if cur_run.status in ("PASSED", "FAILED", "CANCELLED") or (total > 0 and completed >= total):
                        yield "event: done\ndata: {}\n\n"
                        break

                await asyncio.sleep(0.5)
        except Exception as err:
            logger.error("Run SSE error for %s: %s", run_id, err)
            yield f"event: error\ndata: {json.dumps({'message': str(err)})}\n\n"
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


@router.post("/{run_id}/cancel", response_model=RunDetailResponse)
async def cancel_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Cancel all active and queued executions in a run."""
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid run ID")

    run_stmt = select(ValidationRun).where(ValidationRun.id == run_uuid)
    run_res = await db.execute(run_stmt)
    run = run_res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    await _verify_project_access(db, run.project_id, user.id)

    # Cancel all executions
    exec_service = ExecutionService(db)
    for eid_str in run.execution_ids or []:
        try:
            await exec_service.cancel_execution(uuid.UUID(eid_str))
        except Exception as cancel_err:
            logger.warning("Failed to cancel execution %s: %s", eid_str, cancel_err)

    run.status = "CANCELLED"
    run.completed_at = datetime.now(UTC)
    await db.commit()

    return await get_run(run_id=run_id, user=user, db=db)
