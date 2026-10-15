"""Continuous validation service: product knowledge, change impact, execution, and baseline diffs."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.schemas import ExecutionCreate
from app.modules.executions.service import ExecutionService
from app.modules.flows.models import Flow
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.projects.models import Project
from app.modules.validation.impact_analysis import ChangeImpactAnalyzer
from app.modules.validation.models import ProductModel, ValidationRun, ValidationScope, ValidationStatus
from app.modules.validation.schemas import (
    BaselineDiff,
    ImpactReport,
    ProductModelCreate,
    ProductModelUpdate,
    ValidationCreate,
)
from app.modules.validation.selector import RegressionFlowSelector


class ValidationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Product Knowledge Management ---

    async def get_latest_product_model(self, project_id: uuid.UUID) -> ProductModel:
        """Retrieve the most recent product model for a project, creating a default if none exists."""
        stmt = (
            select(ProductModel)
            .where(ProductModel.project_id == project_id)
            .order_by(desc(ProductModel.version))
            .limit(1)
        )
        res = await self.db.execute(stmt)
        model = res.scalar_one_or_none()
        if model:
            return model

        # Seed initial model from project info
        proj_stmt = select(Project).where(Project.id == project_id)
        proj_res = await self.db.execute(proj_stmt)
        project = proj_res.scalar_one_or_none()

        model = ProductModel(
            project_id=project_id,
            version=1,
            name=f"{project.name if project else 'Application'} Model",
            purpose=project.description if project else None,
            capabilities=[
                {
                    "name": "authentication",
                    "description": "User login, signup, and session handling",
                    "routes": ["/login", "/signup"],
                    "source_files": ["app/auth/*", "backend/app/auth/*"],
                    "kind": "shared",
                },
                {
                    "name": "navigation",
                    "description": "Top-level application routing and header navigation",
                    "routes": ["/", "/dashboard"],
                    "source_files": ["frontend/components/Navbar.*"],
                },
            ],
            routes=[
                {"path": "/", "purpose": "Home page"},
                {"path": "/login", "purpose": "Authentication entrance"},
            ],
            roles=[{"role": "user", "description": "Standard authenticated user", "permissions": ["read"]}],
            entities=[],
            metadata_={"seeded": True, "created_at": datetime.now(timezone.utc).isoformat()},
        )
        self.db.add(model)
        await self.db.flush()
        return model

    async def update_product_model(
        self, project_id: uuid.UUID, data: ProductModelUpdate
    ) -> ProductModel:
        """Create a new versioned entry in product model history to preserve knowledge evolution."""
        current = await self.get_latest_product_model(project_id)
        new_version = current.version + 1

        new_model = ProductModel(
            project_id=project_id,
            version=new_version,
            name=data.name or current.name,
            purpose=data.purpose if data.purpose is not None else current.purpose,
            capabilities=data.capabilities if data.capabilities is not None else current.capabilities,
            routes=data.routes if data.routes is not None else current.routes,
            roles=data.roles if data.roles is not None else current.roles,
            entities=data.entities if data.entities is not None else current.entities,
            metadata_=data.metadata if data.metadata is not None else current.metadata_,
        )
        self.db.add(new_model)
        await self.db.flush()
        return new_model

    async def list_product_models(self, project_id: uuid.UUID) -> list[ProductModel]:
        stmt = (
            select(ProductModel)
            .where(ProductModel.project_id == project_id)
            .order_by(desc(ProductModel.version))
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_product_model(self, project_id: uuid.UUID) -> ProductModel | None:
        """Retrieve the latest product model without automatically seeding if none exists."""
        stmt = (
            select(ProductModel)
            .where(ProductModel.project_id == project_id)
            .order_by(desc(ProductModel.version))
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    # --- Change Impact Analysis ---

    async def analyze_impact(
        self,
        project_id: uuid.UUID,
        changed_files: list[str] | None = None,
        diff_content: str | None = None,
        commit_message: str | None = None,
    ) -> ImpactReport:
        repo = ProductGraphRepository(self.db)
        latest_graph = await repo.get_latest_version(project_id)
        graph_dict = latest_graph.snapshot if (latest_graph and latest_graph.snapshot) else None

        model = await self.get_product_model(project_id)
        if not latest_graph and not model:
            model = await self.get_latest_product_model(project_id)
        flows_stmt = select(Flow).where(Flow.project_id == project_id)
        flows_res = await self.db.execute(flows_stmt)
        flows = list(flows_res.scalars().all())

        product_model_dict: dict[str, Any] = {}
        if model and model.capabilities:
            product_model_dict = {
                "capabilities": model.capabilities,
                "routes": model.routes,
                "roles": model.roles,
            }

        analyzer = ChangeImpactAnalyzer(
            product_model=product_model_dict,
            flows=flows,
            product_graph=graph_dict,
        )
        return analyzer.analyze(
            changed_files=changed_files,
            diff_content=diff_content,
            commit_message=commit_message,
        )

    # --- Continuous Validation Runs ---

    async def create_validation_run(self, data: ValidationCreate) -> ValidationRun:
        """Trigger an explainable, risk-aware continuous validation run."""
        # 1. Run change impact analysis
        impact = await self.analyze_impact(
            project_id=data.project_id,
            changed_files=data.changed_files,
            diff_content=data.diff_content,
            commit_message=data.commit_message,
        )

        # 2. Get active flows
        flows_stmt = select(Flow).where(Flow.project_id == data.project_id)
        flows_res = await self.db.execute(flows_stmt)
        flows = list(flows_res.scalars().all())

        # 3. Retrieve failing flows from previous baseline run
        baseline = await self._get_latest_baseline(data.project_id)
        prev_failing = set()
        if baseline and isinstance(baseline.summary, dict):
            prev_failing = set(baseline.summary.get("failed_flow_ids", []))

        # 4. Select flows using Risk-Aware Regression Flow Selector
        selector = RegressionFlowSelector(flows)
        selected_flows, selection_reasons, exclusion_reasons = selector.select(
            impact_report=impact,
            scope=data.scope,
            previously_failing_flow_ids=prev_failing,
        )

        # 5. Persist the ValidationRun
        selected_flow_ids = [str(f.id) for f in selected_flows]
        impact_dict = impact.model_dump()
        impact_dict["selection_reasons"] = selection_reasons
        impact_dict["exclusion_reasons"] = exclusion_reasons

        vrun = ValidationRun(
            project_id=data.project_id,
            commit_sha=data.commit_sha,
            branch=data.branch,
            pr_number=data.pr_number,
            base_url=data.base_url,
            scope=data.scope,
            status=ValidationStatus.RUNNING.value,
            selected_flow_ids=selected_flow_ids,
            execution_ids=[],
            impact_report=impact_dict,
            baseline_run_id=baseline.id if baseline else None,
            baseline_diff={},
            summary={
                "total_flows": len(selected_flow_ids),
                "scope": data.scope,
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        self.db.add(vrun)
        await self.db.flush()

        # 6. Create and dispatch executions for each selected flow
        exec_service = ExecutionService(self.db)
        execution_ids: list[str] = []
        for flow in selected_flows:
            execution = await exec_service.create_execution(
                ExecutionCreate(flow_id=flow.id)
            )
            execution_ids.append(str(execution.id))

        vrun.execution_ids = execution_ids
        await self.db.flush()

        # 7. Configure fail_on_healed if requested
        if data.fail_on_healed:
            from app.engine.execution.control import set_execution_fail_on_healed
            for eid in execution_ids:
                await set_execution_fail_on_healed(eid, True)

        # 8. Dispatch in background
        from app.api.routes.ci import _schedule_dispatch
        for eid in execution_ids:
            _schedule_dispatch(eid)

        return vrun

    async def get_validation_run(self, vrun_id: uuid.UUID) -> ValidationRun | None:
        stmt = select(ValidationRun).where(ValidationRun.id == vrun_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_validation_runs(
        self, project_id: uuid.UUID, limit: int = 50
    ) -> list[ValidationRun]:
        stmt = (
            select(ValidationRun)
            .where(ValidationRun.project_id == project_id)
            .order_by(desc(ValidationRun.created_at))
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def evaluate_validation_run(self, vrun_id: uuid.UUID) -> ValidationRun | None:
        """Poll executions, compute baseline comparison, and finalize exit code when finished."""
        vrun = await self.get_validation_run(vrun_id)
        if not vrun:
            return None

        if vrun.status != ValidationStatus.RUNNING.value and vrun.exit_code is not None:
            return vrun

        if not vrun.execution_ids:
            vrun.status = ValidationStatus.PASSED.value
            vrun.exit_code = 0
            vrun.completed_at = datetime.now(timezone.utc)
            await self.db.flush()
            return vrun

        # Load current status of all executions
        exec_uuids = [uuid.UUID(eid) for eid in vrun.execution_ids]
        stmt = select(Execution).where(Execution.id.in_(exec_uuids))
        res = await self.db.execute(stmt)
        executions = list(res.scalars().all())

        # Map executions by flow_id
        flow_status_map: dict[str, str] = {}
        counts = {"passed": 0, "failed": 0, "blocked": 0, "unverified": 0, "error": 0, "running": 0}
        failed_flow_ids: list[str] = []

        is_all_terminal = True
        for ex in executions:
            s = ex.status.value if hasattr(ex.status, "value") else str(ex.status)
            fid = str(ex.flow_id)
            flow_status_map[fid] = s

            if s == ExecutionStatus.COMPLETED.value:
                counts["passed"] += 1
            elif s == ExecutionStatus.FAILED.value:
                counts["failed"] += 1
                failed_flow_ids.append(fid)
            elif s == ExecutionStatus.BLOCKED.value:
                counts["blocked"] += 1
            elif s == ExecutionStatus.UNVERIFIED.value:
                counts["unverified"] += 1
            elif s in (ExecutionStatus.ERROR.value, ExecutionStatus.CANCELLED.value, ExecutionStatus.TIMEOUT.value):
                counts["error"] += 1
            else:
                counts["running"] += 1
                is_all_terminal = False

        if not is_all_terminal:
            vrun.summary = {**vrun.summary, **counts}
            await self.db.flush()
            return vrun

        # Finalize results & compute Baseline Diff
        baseline = await self._get_latest_baseline(vrun.project_id, exclude_id=vrun.id)
        baseline_flow_status: dict[str, str] = {}
        if baseline and isinstance(baseline.summary, dict):
            baseline_flow_status = baseline.summary.get("flow_status_map", {})

        diff = self._compute_baseline_diff(
            current_map=flow_status_map,
            baseline_map=baseline_flow_status,
            baseline_id=baseline.id if baseline else None,
        )

        # Stable Exit-Code Contract:
        # 0: Validation completed; all required checks passed.
        # 1: One or more required checks failed.
        # 2: Validation could not produce a trustworthy result (blocked, unresolved required checks, unverified).
        # 4: Infrastructure, browser crash, or internal worker failure.
        if counts["failed"] > 0:
            final_status = ValidationStatus.FAILED.value
            exit_code = 1
        elif counts["blocked"] > 0:
            final_status = ValidationStatus.BLOCKED.value
            exit_code = 2
        elif counts["unverified"] > 0:
            final_status = ValidationStatus.UNVERIFIED.value
            exit_code = 2
        elif counts["error"] > 0:
            final_status = ValidationStatus.ERROR.value
            exit_code = 4
        else:
            final_status = ValidationStatus.PASSED.value
            exit_code = 0

        vrun.status = final_status
        vrun.exit_code = exit_code
        vrun.completed_at = datetime.now(timezone.utc)
        vrun.baseline_diff = diff.model_dump()
        vrun.summary = {
            **vrun.summary,
            **counts,
            "failed_flow_ids": failed_flow_ids,
            "flow_status_map": flow_status_map,
            "completed_at": vrun.completed_at.isoformat(),
        }
        await self.db.flush()
        return vrun

    async def _get_latest_baseline(
        self, project_id: uuid.UUID, exclude_id: uuid.UUID | None = None
    ) -> ValidationRun | None:
        """Find the latest finished validation run for baseline comparison."""
        stmt = (
            select(ValidationRun)
            .where(
                ValidationRun.project_id == project_id,
                ValidationRun.status != ValidationStatus.RUNNING.value,
            )
        )
        if exclude_id:
            stmt = stmt.where(ValidationRun.id != exclude_id)
        stmt = stmt.order_by(desc(ValidationRun.created_at)).limit(1)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    def _compute_baseline_diff(
        self,
        current_map: dict[str, str],
        baseline_map: dict[str, str],
        baseline_id: uuid.UUID | None,
    ) -> BaselineDiff:
        newly_failing: list[str] = []
        recovered: list[str] = []
        unchanged_passing: list[str] = []
        blocked: list[str] = []
        unverified: list[str] = []
        status_changed: list[dict] = []

        for flow_id, curr_status in current_map.items():
            prev_status = baseline_map.get(flow_id)

            if curr_status == ExecutionStatus.FAILED.value and prev_status == ExecutionStatus.COMPLETED.value:
                newly_failing.append(flow_id)
            elif curr_status == ExecutionStatus.COMPLETED.value and prev_status == ExecutionStatus.FAILED.value:
                recovered.append(flow_id)
            elif curr_status == ExecutionStatus.COMPLETED.value and prev_status == ExecutionStatus.COMPLETED.value:
                unchanged_passing.append(flow_id)

            if curr_status == ExecutionStatus.BLOCKED.value:
                blocked.append(flow_id)
            if curr_status == ExecutionStatus.UNVERIFIED.value:
                unverified.append(flow_id)

            if prev_status and prev_status != curr_status:
                status_changed.append({
                    "flow_id": flow_id,
                    "previous": prev_status,
                    "current": curr_status,
                })

        return BaselineDiff(
            baseline_run_id=baseline_id,
            newly_failing=newly_failing,
            recovered=recovered,
            unchanged_passing=unchanged_passing,
            blocked=blocked,
            unverified=unverified,
            status_changed=status_changed,
        )
