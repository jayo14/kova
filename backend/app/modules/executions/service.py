"""Execution service for business logic."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.event_service import EventService
from app.modules.executions.models import ExecutionStatus
from app.modules.executions.repository import ExecutionEventRepository, ExecutionRepository
from app.modules.executions.schemas import ExecutionCreate


class ExecutionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExecutionRepository(db)
        self.event_repo = ExecutionEventRepository(db)
        self.event_service = EventService(db)

    async def create_execution(self, data: ExecutionCreate, *, flow_version: int = 1, flow_snapshot: dict | None = None, mode: str | None = None):
        """Create a new execution record, inheriting validation mode from the flow."""
        if mode is None:
            try:
                from sqlalchemy import select
                from app.modules.flows.models import Flow
                f_res = await self.db.execute(select(Flow.mode).where(Flow.id == data.flow_id))
                mode_val = f_res.scalar_one_or_none()
                if mode_val:
                    mode = mode_val
            except Exception:
                pass
        execution = await self.repo.create(
            flow_id=data.flow_id,
            flow_version=flow_version,
            flow_snapshot=flow_snapshot,
            mode=mode or "functional",
        )
        await self.event_service.record_execution_created(execution.id)

        try:
            from sqlalchemy import select
            from app.modules.billing.repository import BillingRepository
            from app.modules.flows.models import Flow
            from app.modules.projects.models import Project

            f_res = await self.db.execute(select(Flow).where(Flow.id == data.flow_id))
            flow = f_res.scalar_one_or_none()
            if flow:
                p_res = await self.db.execute(select(Project).where(Project.id == flow.project_id))
                project = p_res.scalar_one_or_none()
                if project and project.org_id:
                    billing_repo = BillingRepository(self.db)
                    await billing_repo.record_usage_event(
                        org_id=project.org_id,
                        execution_id=execution.id,
                        plan_at_time="free",
                    )
        except Exception:
            pass

        return execution

    async def get_execution(self, execution_id: uuid.UUID):
        """Get execution by ID."""
        return await self.repo.get_by_id(execution_id)

    async def list_executions(self, flow_id: uuid.UUID, skip: int = 0, limit: int = 100):
        """List executions for a flow."""
        return await self.repo.list_by_flow(flow_id, skip=skip, limit=limit)

    async def list_all(self, skip: int = 0, limit: int = 100):
        """List all executions."""
        return await self.repo.list_all(skip=skip, limit=limit)

    async def cancel_execution(self, execution_id: uuid.UUID):
        """Cancel an execution.

        Updates status to CANCELLED and records event.
        """
        await self.repo.update_status(execution_id, ExecutionStatus.CANCELLED)
        await self.event_service.record_execution_cancelled(execution_id)

    async def get_events(self, execution_id: uuid.UUID, skip: int = 0, limit: int = 1000):
        """Get events for an execution."""
        return await self.event_repo.list_by_execution(execution_id, skip=skip, limit=limit)

    async def batch_execute(
        self,
        project_id: uuid.UUID,
        plan: Any,
        base_url: str | None = None,
        timeout_seconds: int = 1800,
    ) -> list[dict[str, Any]]:
        """Run an execution plan as a single batch with shared session and prerequisite tracking."""
        import time
        from sqlalchemy import select
        from app.modules.flows.models import Flow
        from app.modules.executions.evidence_model import Evidence

        results: list[dict[str, Any]] = []
        steps = getattr(plan, "steps", []) or []
        prereq_failed = False
        prereq_failure_reason = None

        for step in steps:
            flow_id_str = getattr(step, "flow_id", str(step))
            flow_name = getattr(step, "flow_name", "") or flow_id_str
            role = getattr(step, "role", "target")
            establishes = getattr(step, "establishes", []) or []
            state_changes = {getattr(e, "key", str(e)): getattr(e, "value", True) for e in establishes}

            try:
                flow_uuid = uuid.UUID(flow_id_str)
            except (ValueError, TypeError):
                flow_uuid = None

            flow = None
            if flow_uuid:
                flow_res = await self.repo.db.execute(select(Flow).where(Flow.id == flow_uuid))
                flow = flow_res.scalar_one_or_none()
                if flow and not flow_name:
                    flow_name = flow.name

            # If a prior prerequisite failed, skip remaining targets
            if prereq_failed:
                results.append(
                    {
                        "flow_id": str(flow_uuid or uuid.uuid4()),
                        "flow_name": flow_name,
                        "role": role,
                        "status": "skipped",
                        "duration_ms": 0,
                        "evidence_ids": [],
                        "failure_reason": f"Skipped because prerequisite failed: {prereq_failure_reason}",
                        "state_changes": {},
                    }
                )
                continue

            # Create execution row in DB
            execution = None
            if flow:
                execution = await self.create_execution(
                    ExecutionCreate(flow_id=flow.id),
                    flow_version=getattr(flow, "version", 1),
                    flow_snapshot=getattr(flow, "json_repr", None),
                )
                await self.repo.update_status(execution.id, ExecutionStatus.PLANNING)
                await self.repo.update_status(execution.id, ExecutionStatus.RUNNING)
                await self.repo.db.commit()

            start_t = time.monotonic()
            step_status = "passed"
            failure_reason = None
            evidence_ids: list[uuid.UUID] = []

            # Execute via FlowRunner if steps exist and not mocked
            if flow and getattr(flow, "steps", None):
                try:
                    from app.engine.execution.runner import FlowRunner
                    runner = FlowRunner()
                    res = await runner.execute(
                        execution_id=execution.id,
                        flow_steps=flow.steps,
                        success_condition=getattr(flow, "success_condition", None),
                        preconditions=getattr(flow, "preconditions", None),
                        target_url=base_url or "",
                        timeout_seconds=min(300, timeout_seconds),
                    )
                    if res.get("success"):
                        step_status = "passed"
                        if execution:
                            await self.repo.update_status(execution.id, ExecutionStatus.COMPLETED)
                    elif res.get("error_code") == "UNVERIFIED":
                        step_status = "unverified"
                        failure_reason = res.get("error", "Verification condition unverified")
                        if execution:
                            await self.repo.update_status(execution.id, ExecutionStatus.UNVERIFIED)
                    else:
                        step_status = "failed"
                        failure_reason = res.get("error", "Flow step failed")
                        if execution:
                            await self.repo.update_status(execution.id, ExecutionStatus.FAILED)
                except Exception as ex:
                    step_status = "failed"
                    failure_reason = str(ex)
                    if execution:
                        await self.repo.update_status(execution.id, ExecutionStatus.FAILED)

            duration_ms = int((time.monotonic() - start_t) * 1000)

            # Query any evidence records created for this execution
            if execution:
                ev_res = await self.repo.db.execute(
                    select(Evidence.id).where(Evidence.execution_id == execution.id)
                )
                evidence_ids = list(ev_res.scalars().all())

            if role == "prerequisite" and step_status in ("failed", "error"):
                prereq_failed = True
                prereq_failure_reason = failure_reason or f"Prerequisite {flow_name} failed"

            results.append(
                {
                    "flow_id": str(flow_uuid or (flow.id if flow else uuid.uuid4())),
                    "flow_name": flow_name,
                    "role": role,
                    "status": step_status,
                    "duration_ms": duration_ms,
                    "evidence_ids": evidence_ids,
                    "failure_reason": failure_reason,
                    "state_changes": state_changes,
                }
            )

        return results
