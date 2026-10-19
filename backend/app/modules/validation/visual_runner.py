"""Visual validation runner using pixel diff, layout clustering, a11y tree diff, and VLM."""
from __future__ import annotations

import base64
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select

from app.config.settings import settings
from app.engine.visual.schemas import VisualReference, VisualValidationResult
from app.engine.visual.validator import VisualValidator
from app.engine.visual.vlm_client import VLMClient
from app.modules.validation.models import ValidationMode, VisualReferenceModel
from app.modules.validation.schemas import (
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)
from app.modules.validation.success_criteria import SUCCESS_CRITERIA, SuccessCriteria

logger = logging.getLogger(__name__)


class VisualRunner:
    """Executes visual validation for flows comparing against a baseline visual reference."""

    def __init__(
        self,
        criteria: SuccessCriteria | None = None,
        db: Any = None,
        execution_service: Any = None,
        validator: VisualValidator | None = None,
    ):
        self.criteria = criteria or SUCCESS_CRITERIA[ValidationMode.VISUAL]
        self.db = db
        self.execution_service = execution_service

        if validator:
            self.validator = validator
        else:
            vlm_client = None
            if getattr(settings, "VLM_ENABLED", False):
                vlm_client = VLMClient(
                    model=getattr(settings, "VLM_MODEL", "gpt-4o-mini"),
                    api_key=getattr(settings, "VLM_API_KEY", ""),
                    base_url=getattr(settings, "VLM_BASE_URL", "https://api.openai.com/v1"),
                )
            self.validator = VisualValidator(vlm_client=vlm_client)

    async def _get_visual_reference(self, flow_id: uuid.UUID) -> VisualReference | None:
        """Fetch the latest baseline visual reference for a flow from the database."""
        if not self.db:
            return None
        stmt = (
            select(VisualReferenceModel)
            .where(VisualReferenceModel.flow_id == flow_id)
            .order_by(desc(VisualReferenceModel.captured_at))
            .limit(1)
        )
        res = await self.db.execute(stmt)
        row = res.scalar_one_or_none()
        if not row:
            return None
        return VisualReference(
            id=row.id,
            flow_id=row.flow_id,
            screenshot_url=row.screenshot_url,
            a11y_tree=row.a11y_tree or {},
            viewport=row.viewport or {"width": 1280, "height": 720},
            captured_at=row.captured_at,
            label=row.label or "Baseline",
        )

    async def run(
        self,
        request: ValidationRequest,
        plan: Any | None = None,
        impact_report: ImpactReport | None = None,
        current_screenshot_bytes: bytes | None = None,
        current_a11y_tree: dict | list | None = None,
    ) -> ValidationReport:
        started_at = datetime.now(timezone.utc)
        start_time = time.time()

        target_steps = [s for s in getattr(plan, "steps", []) if getattr(s, "role", "") == "target"] if plan else []
        flow_id = None
        flow_name = "Visual Flow"

        if target_steps:
            s = target_steps[0]
            flow_id = uuid.UUID(str(s.flow_id)) if hasattr(s, "flow_id") else None
            flow_name = getattr(s, "flow_name", "Visual Flow")
        elif getattr(request, "flow_ids", None):
            flow_id = request.flow_ids[0]
        else:
            flow_id = uuid.uuid4()

        # 1. Fetch visual reference
        reference: VisualReference | None = None
        if hasattr(request, "visual_reference") and getattr(request, "visual_reference"):
            ref_data = getattr(request, "visual_reference")
            reference = ref_data if isinstance(ref_data, VisualReference) else VisualReference(**ref_data)
        elif flow_id:
            reference = await self._get_visual_reference(flow_id)

        if not reference:
            reason = "No visual reference uploaded. Upload a baseline via POST /api/v1/flows/{id}/visual-reference (Action 10)."
            return ValidationReport(
                request=request,
                impact_report=impact_report or ImpactReport(),
                results=[
                    FlowValidationResult(
                        flow_id=flow_id or uuid.uuid4(),
                        flow_name=flow_name,
                        role="target",
                        status="unverified",
                        failure_reason=reason,
                    )
                ],
                overall_status="unverified",
                failure_reason=reason,
                duration_ms=int((time.time() - start_time) * 1000),
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
            )

        # 2. Obtain current screenshot and a11y tree
        curr_bytes = current_screenshot_bytes or getattr(request, "current_screenshot_bytes", None)
        curr_a11y = current_a11y_tree or getattr(request, "current_a11y_tree", None) or {}

        if not curr_bytes:
            # Check if execution_service or browser session provides it
            if self.execution_service and hasattr(self.execution_service, "capture_screenshot"):
                curr_bytes = await self.execution_service.capture_screenshot()
            else:
                # 1x1 blank PNG if not provided
                curr_bytes = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                )

        # 3. Validate
        result = await self.validator.validate(
            reference=reference,
            current_screenshot_bytes=curr_bytes,
            current_a11y_tree=curr_a11y,
            current_viewport=reference.viewport,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        failure_reason = None
        if result.overall_status != "passed":
            failure_reason = f"{len(result.defects)} visual defect(s) detected (pixel diff: {result.pixel_diff_percentage}%)"

        flow_result = FlowValidationResult(
            flow_id=flow_id or uuid.uuid4(),
            flow_name=flow_name,
            role="target",
            status=result.overall_status,
            duration_ms=duration_ms,
            evidence_ids=[],
            failure_reason=failure_reason,
            state_changes={"visual_result": result.model_dump(mode="json")},
        )

        return ValidationReport(
            request=request,
            impact_report=impact_report or ImpactReport(),
            results=[flow_result],
            overall_status=result.overall_status,
            failure_reason=failure_reason,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
