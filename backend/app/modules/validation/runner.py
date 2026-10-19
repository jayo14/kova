"""Validation runner orchestrating execution across validation modes."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.service import ExecutionService
from app.modules.flows.dependency_resolver import ExecutionPlan
from app.modules.validation.exploratory_runner import ExploratoryRunner
from app.modules.validation.functional_runner import FunctionalRunner
from app.modules.validation.models import ValidationMode
from app.modules.validation.regression_runner import RegressionRunner
from app.modules.validation.schemas import (
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)
from app.modules.validation.success_criteria import SUCCESS_CRITERIA, SuccessCriteria
from app.modules.validation.visual_runner import VisualRunner
from app.modules.validation.workflow_runner import WorkflowRunner


class ValidationRunner:
    """Orchestrates validation execution by dispatching to the appropriate sub-runner based on ValidationMode."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        execution_service: ExecutionService | None = None,
        criteria: SuccessCriteria | None = None,
    ):
        self.db = db
        self.execution_service = execution_service or (ExecutionService(db) if db is not None else None)
        self.criteria = criteria

    async def run(
        self,
        request: ValidationRequest,
        plan: ExecutionPlan | None = None,
        impact_report: ImpactReport | None = None,
        **kwargs: Any,
    ) -> ValidationReport:
        # Determine mode
        req_mode = getattr(request, "mode", None)
        target_flow = getattr(plan, "target_flow", None) if plan else None
        target_flow_mode = getattr(target_flow, "mode", None) if target_flow else None

        raw_mode = req_mode or target_flow_mode
        if raw_mode is None:
            # CI runs with changed_files or diff/diff_content default to REGRESSION; otherwise FUNCTIONAL
            if getattr(request, "changed_files", None) or getattr(request, "diff", None) or getattr(request, "diff_content", None):
                raw_mode = ValidationMode.REGRESSION
            else:
                raw_mode = ValidationMode.FUNCTIONAL

        if isinstance(raw_mode, str):
            try:
                mode = ValidationMode(raw_mode.lower())
            except ValueError:
                mode = ValidationMode.FUNCTIONAL
        else:
            mode = raw_mode

        criteria = self.criteria or SUCCESS_CRITERIA.get(mode, SUCCESS_CRITERIA[ValidationMode.FUNCTIONAL])

        if mode == ValidationMode.REGRESSION:
            runner = RegressionRunner(criteria=criteria, db=self.db, execution_service=self.execution_service)
            report = await runner.run(request, plan=plan, impact_report=impact_report, **kwargs)
        elif mode == ValidationMode.EXPLORATORY:
            runner = ExploratoryRunner(criteria=criteria, db=self.db, execution_service=self.execution_service)
            report = await runner.run(request, plan=plan, impact_report=impact_report, **kwargs)
        elif mode == ValidationMode.WORKFLOW:
            runner = WorkflowRunner(criteria=criteria, db=self.db, execution_service=self.execution_service)
            report = await runner.run(request, plan=plan, impact_report=impact_report, **kwargs)
        elif mode == ValidationMode.VISUAL:
            runner = VisualRunner(criteria=criteria, db=self.db, execution_service=self.execution_service)
            report = await runner.run(request, plan=plan, impact_report=impact_report, **kwargs)
        else:  # FUNCTIONAL
            runner = FunctionalRunner(criteria=criteria, db=self.db, execution_service=self.execution_service)
            report = await runner.run(request, plan=plan, impact_report=impact_report, **kwargs)

        # AI Failure Diagnosis and Report Synthesis (§5 capabilities E & H)
        try:
            from app.engine.ai.reasoner import AgentReasoner
            from app.engine.ai.provider import get_ai_provider
            reasoner = AgentReasoner(get_ai_provider())

            for res in report.results:
                if res.status == "failed" and res.hypothesis is None:
                    res.hypothesis = await reasoner.propose_failure_hypothesis(
                        execution_id=str(res.flow_id),
                        events=[],
                        verification_checks=[
                            {
                                "name": res.flow_name,
                                "verdict": "failed",
                                "reason": res.failure_reason or "Flow validation assertion failed",
                                "evidence_ids": [str(eid) for eid in res.evidence_ids],
                            }
                        ],
                        evidence_summary=report.evidence_summary or {},
                    )
            if report.summary is None:
                report.summary = await reasoner.synthesize_report_summary(report.model_dump())
        except Exception:
            pass

        return report

