"""Targeted regression planner connecting git diffs to minimal execution plans."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.dependency_resolver import ExecutionPlan
from app.modules.validation.impact_analysis import ChangeImpactAnalyzer
from app.modules.validation.schemas import ImpactReport, ValidationRequest
from app.modules.validation.service import ValidationService


class TargetedRegressionPlanner:
    """Wraps change impact analysis to compute targeted execution plans for CI validation."""

    def __init__(self, db: AsyncSession | None = None, product_graph: Any | None = None):
        self.db = db
        self.product_graph = product_graph

    async def plan(self, request: ValidationRequest) -> tuple[ImpactReport, ExecutionPlan | None]:
        if self.product_graph is not None:
            analyzer = ChangeImpactAnalyzer(product_graph=self.product_graph)
            impact = analyzer.analyze(
                changed_files=request.changed_files,
                diff_content=request.diff_content,
                commit_message=request.commit_message,
                persona=request.persona,
            )
            return impact, impact.minimal_execution_plan

        if self.db is not None:
            from sqlalchemy import select
            from app.modules.flows.models import Flow
            from app.modules.product_graph.repository import ProductGraphRepository

            repo = ProductGraphRepository(self.db)
            latest_graph = await repo.get_latest_version(request.project_id)
            if not latest_graph or not latest_graph.snapshot:
                val_service = ValidationService(self.db)
                model = await val_service.get_product_model(request.project_id)
                if not model or not model.capabilities:
                    analyzer = ChangeImpactAnalyzer(product_graph={})
                    impact = analyzer.analyze(
                        changed_files=request.changed_files,
                        diff_content=request.diff_content,
                        commit_message=request.commit_message,
                        persona=request.persona,
                    )
                    return impact, None

            flows_stmt = select(Flow).where(Flow.project_id == request.project_id)
            flows_res = await self.db.execute(flows_stmt)
            flows = list(flows_res.scalars().all())

            val_service = ValidationService(self.db)
            impact = await val_service.analyze_impact(
                project_id=request.project_id,
                changed_files=request.changed_files,
                diff_content=request.diff_content,
                commit_message=request.commit_message,
            )
            return impact, impact.minimal_execution_plan

        # Fallback to empty
        analyzer = ChangeImpactAnalyzer(product_graph={})
        impact = analyzer.analyze(
            changed_files=request.changed_files,
            diff_content=request.diff_content,
            commit_message=request.commit_message,
            persona=request.persona,
        )
        return impact, impact.minimal_execution_plan
