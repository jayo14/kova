"""Result aggregator for batch flow validation runs."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from app.modules.validation.schemas import (
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)


class ResultAggregator:
    """Aggregates per-flow execution results into a comprehensive ValidationReport."""

    def aggregate(
        self,
        request: ValidationRequest,
        impact_report: ImpactReport,
        batch_results: list[dict[str, Any]],
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> ValidationReport:
        t_start = started_at or datetime.now(timezone.utc)
        t_finish = finished_at or datetime.now(timezone.utc)
        duration_ms = max(0, int((t_finish - t_start).total_seconds() * 1000))

        # 1. Fail-closed: check if Product Graph was missing
        if impact_report.confidence == 0.0 and not impact_report.product_graph_consulted:
            return ValidationReport(
                request=request,
                impact_report=impact_report,
                results=[],
                overall_status="no_graph",
                duration_ms=duration_ms,
                started_at=t_start,
                finished_at=t_finish,
                evidence_summary={},
            )

        # 2. Check if no flows were affected
        if not batch_results and not impact_report.affected_flows:
            return ValidationReport(
                request=request,
                impact_report=impact_report,
                results=[],
                overall_status="no_flows",
                duration_ms=duration_ms,
                started_at=t_start,
                finished_at=t_finish,
                evidence_summary={},
            )

        flow_results: list[FlowValidationResult] = []
        evidence_summary: dict[str, int] = {}
        target_results: list[FlowValidationResult] = []
        any_prereq_failed = False

        for res in batch_results:
            fid_raw = res.get("flow_id")
            fid = uuid.UUID(str(fid_raw)) if fid_raw else uuid.uuid4()
            fname = res.get("flow_name", str(fid))
            role = res.get("role", "target")
            status = res.get("status", "passed")
            duration = int(res.get("duration_ms", 0))
            failure_reason = res.get("failure_reason")
            state_changes = res.get("state_changes", {})

            # Parse evidence IDs
            raw_ev_ids = res.get("evidence_ids", [])
            evidence_ids: list[uuid.UUID] = []
            for ev in raw_ev_ids:
                try:
                    evidence_ids.append(uuid.UUID(str(ev)))
                except (ValueError, TypeError):
                    continue

            # Update evidence summary counts
            ev_counts = res.get("evidence_counts", {})
            if isinstance(ev_counts, dict):
                for k, count in ev_counts.items():
                    evidence_summary[k] = evidence_summary.get(k, 0) + int(count)
            elif evidence_ids:
                evidence_summary["evidence_items"] = (
                    evidence_summary.get("evidence_items", 0) + len(evidence_ids)
                )

            flow_res = FlowValidationResult(
                flow_id=fid,
                flow_name=fname,
                role=role,
                status=status,
                duration_ms=duration,
                evidence_ids=evidence_ids,
                failure_reason=failure_reason,
                state_changes=state_changes,
            )

            if role == "prerequisite":
                if status in ("failed", "error", "unverified"):
                    any_prereq_failed = True
                    flow_results.append(flow_res)
                # Passing prerequisites are omitted to avoid report pollution
            else:
                target_results.append(flow_res)
                flow_results.append(flow_res)

        # 3. Compute overall status
        overall_status: Literal["passed", "failed", "unverified", "no_graph", "no_flows"]
        if not target_results:
            overall_status = "no_flows"
        elif any_prereq_failed or any(tr.status in ("failed", "error") for tr in target_results):
            overall_status = "failed"
        elif any(tr.status == "unverified" for tr in target_results):
            overall_status = "unverified"
        else:
            overall_status = "passed"

        return ValidationReport(
            request=request,
            impact_report=impact_report,
            results=flow_results,
            overall_status=overall_status,
            duration_ms=duration_ms,
            started_at=t_start,
            finished_at=t_finish,
            evidence_summary=evidence_summary,
        )
