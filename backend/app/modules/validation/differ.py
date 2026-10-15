"""Differential analysis between ValidationReport instances."""
from __future__ import annotations

import uuid
from typing import Dict

from app.modules.validation.schemas import (
    FlowResultDiff,
    FlowValidationResult,
    ReportDiff,
    ValidationReport,
)


class ReportDiffer:
    """Computes deterministic diffs between two validation reports."""

    @staticmethod
    def diff(report_before: ValidationReport, report_after: ValidationReport) -> ReportDiff:
        before_by_id: Dict[uuid.UUID, FlowValidationResult] = {
            res.flow_id: res for res in report_before.results
        }
        after_by_id: Dict[uuid.UUID, FlowValidationResult] = {
            res.flow_id: res for res in report_after.results
        }

        flows_added: list[FlowValidationResult] = []
        flows_removed: list[FlowValidationResult] = []
        flows_changed: list[FlowResultDiff] = []
        flows_unchanged: list[FlowValidationResult] = []

        # Check flows in after
        for flow_id, after_res in after_by_id.items():
            if flow_id not in before_by_id:
                flows_added.append(after_res)
            else:
                before_res = before_by_id[flow_id]
                status_changed = before_res.status != after_res.status
                failure_reason_changed = before_res.failure_reason != after_res.failure_reason

                before_ev = set(before_res.evidence_ids)
                after_ev = set(after_res.evidence_ids)
                new_evidence_count = len(after_ev - before_ev)
                removed_evidence_count = len(before_ev - after_ev)
                evidence_count_changed = (new_evidence_count > 0) or (removed_evidence_count > 0) or (len(before_res.evidence_ids) != len(after_res.evidence_ids))

                if status_changed or failure_reason_changed or evidence_count_changed:
                    flows_changed.append(
                        FlowResultDiff(
                            flow_id=flow_id,
                            flow_name=after_res.flow_name,
                            status_before=before_res.status,
                            status_after=after_res.status,
                            status_changed=status_changed,
                            new_evidence_count=new_evidence_count,
                            removed_evidence_count=removed_evidence_count,
                            failure_reason_before=before_res.failure_reason,
                            failure_reason_after=after_res.failure_reason,
                            failure_reason_changed=failure_reason_changed,
                        )
                    )
                else:
                    flows_unchanged.append(after_res)

        # Check flows in before that are no longer in after
        for flow_id, before_res in before_by_id.items():
            if flow_id not in after_by_id:
                flows_removed.append(before_res)

        overall_status_changed = report_before.overall_status != report_after.overall_status

        return ReportDiff(
            report_before=report_before,
            report_after=report_after,
            overall_status_changed=overall_status_changed,
            flows_added=flows_added,
            flows_removed=flows_removed,
            flows_changed=flows_changed,
            flows_unchanged=flows_unchanged,
        )
