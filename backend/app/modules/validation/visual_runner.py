"""Visual validation runner stub. Real implementation arrives in Action 10."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.modules.validation.models import ValidationMode
from app.modules.validation.schemas import (
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)
from app.modules.validation.success_criteria import SUCCESS_CRITERIA, SuccessCriteria


class VisualRunner:
    """Stub runner for Visual Validation mode. Full implementation in Action 10."""

    def __init__(
        self,
        criteria: SuccessCriteria | None = None,
        db: Any = None,
        execution_service: Any = None,
    ):
        self.criteria = criteria or SUCCESS_CRITERIA[ValidationMode.VISUAL]
        self.db = db
        self.execution_service = execution_service

    async def run(
        self,
        request: ValidationRequest,
        plan: Any | None = None,
        impact_report: ImpactReport | None = None,
    ) -> ValidationReport:
        started_at = datetime.now(timezone.utc)
        message = "Visual validation not yet implemented. See action 10."

        target_steps = [s for s in getattr(plan, "steps", []) if getattr(s, "role", "") == "target"] if plan else []
        results = [
            FlowValidationResult(
                flow_id=uuid.UUID(str(s.flow_id)) if hasattr(s, "flow_id") else uuid.uuid4(),
                flow_name=getattr(s, "flow_name", "Visual Flow"),
                role="target",
                status="unverified",
                failure_reason=message,
            )
            for s in target_steps
        ]

        return ValidationReport(
            request=request,
            impact_report=impact_report or ImpactReport(),
            results=results,
            overall_status="unverified",
            failure_reason=message,
            duration_ms=0,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            evidence_summary={"failure_reason": message},
        )
