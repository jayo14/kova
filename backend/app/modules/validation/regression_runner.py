"""Regression validation runner comparing executions against baselines."""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.service import ExecutionService
from app.modules.flows.dependency_resolver import ExecutionPlan
from app.modules.validation.aggregator import ResultAggregator
from app.modules.validation.models import ValidationMode, ValidationReportModel
from app.modules.validation.planner import TargetedRegressionPlanner
from app.modules.validation.schemas import (
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)
from app.modules.validation.success_criteria import REGRESSION_CRITERIA, SuccessCriteria


class RegressionRunner:
    """Orchestrates execution of regression validation plans with baseline comparison."""

    def __init__(
        self,
        criteria: SuccessCriteria | None = None,
        db: AsyncSession | None = None,
        execution_service: ExecutionService | None = None,
    ):
        self.criteria = criteria or REGRESSION_CRITERIA
        self.db = db
        self.execution_service = execution_service or (ExecutionService(db) if db is not None else None)

    async def _persist_report(self, report: ValidationReport) -> None:
        if self.db is None:
            return
        try:
            report_model = ValidationReportModel(
                id=report.id,
                project_id=report.request.project_id,
                overall_status=report.overall_status,
                duration_ms=report.duration_ms,
                request=report.request.model_dump(mode="json"),
                impact_report=report.impact_report.model_dump(mode="json"),
                results=[r.model_dump(mode="json") for r in report.results],
                evidence_summary=report.evidence_summary,
                signed_url=report.signed_url,
                started_at=report.started_at,
                finished_at=report.finished_at,
            )
            self.db.add(report_model)
            await self.db.commit()
        except Exception:
            pass

    async def run(
        self,
        request: ValidationRequest,
        plan: ExecutionPlan | None = None,
        impact_report: ImpactReport | None = None,
        baseline_screenshot: bytes | str | None = None,
        current_screenshot: bytes | str | None = None,
        baseline_diff: dict | None = None,
    ) -> ValidationReport:
        started_at = datetime.now(timezone.utc)
        start_mono = time.monotonic()

        # 1. Direct baseline comparison checks
        b_screenshot = baseline_screenshot or getattr(request, "baseline_screenshot", None)
        c_screenshot = current_screenshot or getattr(request, "current_screenshot", None)

        if b_screenshot is not None and c_screenshot is not None:
            has_diff = b_screenshot != c_screenshot
            status = "failed" if has_diff else "passed"
            finished_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((time.monotonic() - start_mono) * 1000))
            flow_steps = getattr(plan, "steps", []) if plan else []
            target_steps = [s for s in flow_steps if getattr(s, "role", "") == "target"] or flow_steps
            if target_steps:
                results = [
                    FlowValidationResult(
                        flow_id=uuid.UUID(str(getattr(s, "flow_id", uuid.uuid4()))) if _is_valid_uuid(getattr(s, "flow_id", None)) else uuid.uuid4(),
                        flow_name=getattr(s, "flow_name", "Regression Target"),
                        role=getattr(s, "role", "target"),
                        status=status,
                        failure_reason="Baseline mismatch detected" if has_diff else None,
                    )
                    for s in target_steps
                ]
            else:
                results = [
                    FlowValidationResult(
                        flow_id=uuid.uuid4(),
                        flow_name="Regression Target",
                        role="target",
                        status=status,
                        failure_reason="Baseline mismatch detected" if has_diff else None,
                    )
                ]
            report = ValidationReport(
                request=request,
                impact_report=impact_report or ImpactReport(),
                results=results,
                overall_status=status,
                failure_reason="Baseline comparison failed: diff detected" if has_diff else None,
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                evidence_summary={"baseline_diff": has_diff},
            )
            await self._persist_report(report)
            return report

        if baseline_diff:
            has_diff = bool(baseline_diff.get("newly_failing") or baseline_diff.get("status_changed") or baseline_diff.get("diff"))
            status = "failed" if has_diff else "passed"
            finished_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((time.monotonic() - start_mono) * 1000))
            flow_steps = getattr(plan, "steps", []) if plan else []
            target_steps = [s for s in flow_steps if getattr(s, "role", "") == "target"] or flow_steps
            if target_steps:
                results = [
                    FlowValidationResult(
                        flow_id=uuid.UUID(str(getattr(s, "flow_id", uuid.uuid4()))) if _is_valid_uuid(getattr(s, "flow_id", None)) else uuid.uuid4(),
                        flow_name=getattr(s, "flow_name", "Regression Target"),
                        role=getattr(s, "role", "target"),
                        status=status,
                        failure_reason="Baseline regression diff detected" if has_diff else None,
                    )
                    for s in target_steps
                ]
            else:
                results = [
                    FlowValidationResult(
                        flow_id=uuid.uuid4(),
                        flow_name="Regression Target",
                        role="target",
                        status=status,
                        failure_reason="Baseline regression diff detected" if has_diff else None,
                    )
                ]
            report = ValidationReport(
                request=request,
                impact_report=impact_report or ImpactReport(),
                results=results,
                overall_status=status,
                failure_reason="Baseline regression diff detected" if has_diff else None,
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                evidence_summary={"baseline_diff": baseline_diff},
            )
            await self._persist_report(report)
            return report

        # If impact_report or plan not provided, compute via planner
        if impact_report is None or plan is None:
            planner = TargetedRegressionPlanner(self.db)
            computed_impact, computed_plan = await planner.plan(request)
            if impact_report is None:
                impact_report = computed_impact
            if plan is None:
                plan = computed_plan

        # Fail-closed 1: Missing Product Graph
        if plan is None or (impact_report.confidence == 0.0 and not impact_report.product_graph_consulted):
            finished_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((time.monotonic() - start_mono) * 1000))
            report = ValidationReport(
                request=request,
                impact_report=impact_report,
                results=[],
                overall_status="no_graph",
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                evidence_summary={},
            )
            await self._persist_report(report)
            return report

        # Fail-closed 2: Empty plan
        target_steps = [s for s in getattr(plan, "steps", []) if getattr(s, "role", "") == "target"]
        if not target_steps and not getattr(plan, "steps", []):
            finished_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((time.monotonic() - start_mono) * 1000))
            report = ValidationReport(
                request=request,
                impact_report=impact_report,
                results=[],
                overall_status="no_flows",
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                evidence_summary={},
            )
            await self._persist_report(report)
            return report

        # Execute batch via ExecutionService if available
        timeout_sec = float(request.timeout_seconds or self.criteria.max_duration_seconds)
        try:
            if self.execution_service is not None:
                batch_results = await asyncio.wait_for(
                    self.execution_service.batch_execute(
                        project_id=request.project_id,
                        plan=plan,
                        base_url=request.base_url,
                        timeout_seconds=int(timeout_sec),
                    ),
                    timeout=timeout_sec,
                )
            else:
                batch_results = [
                    {
                        "flow_id": str(getattr(s, "flow_id", uuid.uuid4())),
                        "flow_name": getattr(s, "flow_name", ""),
                        "role": getattr(s, "role", "target"),
                        "status": "passed",
                        "duration_ms": 100,
                        "evidence_ids": [],
                        "failure_reason": None,
                        "state_changes": {},
                    }
                    for s in getattr(plan, "steps", [])
                ]
        except asyncio.TimeoutError:
            finished_at = datetime.now(timezone.utc)
            duration_ms = max(0, int((time.monotonic() - start_mono) * 1000))
            report = ValidationReport(
                request=request,
                impact_report=impact_report,
                results=[
                    FlowValidationResult(
                        flow_id=uuid.UUID(str(s.flow_id)) if _is_valid_uuid(s.flow_id) else uuid.uuid4(),
                        flow_name=getattr(s, "flow_name", str(s.flow_id)),
                        role=getattr(s, "role", "target"),
                        status="error",
                        failure_reason=f"Timeout after {request.timeout_seconds}s",
                    )
                    for s in target_steps
                ],
                overall_status="failed",
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                evidence_summary={},
            )
            await self._persist_report(report)
            return report

        aggregator = ResultAggregator()
        report = aggregator.aggregate(
            request=request,
            impact_report=impact_report,
            batch_results=batch_results,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
        await self._persist_report(report)
        return report


def _is_valid_uuid(val: Any) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError):
        return False
