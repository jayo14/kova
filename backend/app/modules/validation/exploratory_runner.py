"""Exploratory validation runner using agent loop to uncover unexpected behaviors."""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.event_types import EventTypes
from app.modules.executions.service import ExecutionService
from app.modules.flows.dependency_resolver import ExecutionPlan
from app.modules.validation.models import ValidationMode
from app.modules.validation.schemas import (
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)
from app.modules.validation.success_criteria import EXPLORATORY_CRITERIA, SuccessCriteria


class ExploratoryRunner:
    """Exploratory validation runner.
    
    Does NOT compare against a baseline. Uses the agent loop with high turn limit (80 turns)
    to discover unexpected behaviors. Discovered defects count as a SUCCESS for exploratory validation.
    """

    def __init__(
        self,
        criteria: SuccessCriteria | None = None,
        db: AsyncSession | None = None,
        execution_service: ExecutionService | None = None,
    ):
        self.criteria = criteria or EXPLORATORY_CRITERIA
        self.db = db
        self.execution_service = execution_service

    async def run(
        self,
        request: ValidationRequest,
        plan: ExecutionPlan | None = None,
        impact_report: ImpactReport | None = None,
        browser: Any | None = None,
        agent_executor: Any | None = None,
        discovered_defects: list[dict[str, Any]] | None = None,
        event_emitter: Callable[[str, dict], Any] | None = None,
    ) -> ValidationReport:
        started_at = datetime.now(timezone.utc)
        start_mono = time.monotonic()

        target_flow = getattr(plan, "target_flow", None) if plan else None
        target_flow_id = getattr(target_flow, "id", None) or uuid.uuid4()
        target_flow_name = getattr(target_flow, "name", "Exploratory Feature")
        feature_name = getattr(target_flow, "name", None) or getattr(request, "feature_name", "target feature")

        objective = f"discover unexpected behaviors in {feature_name}"
        defects: list[dict[str, Any]] = list(discovered_defects or [])

        # If defects were passed via request
        if hasattr(request, "discovered_defects") and request.discovered_defects:
            defects.extend(request.discovered_defects)

        # 1. Run agent loop if agent_executor or browser provided
        if agent_executor is not None:
            # Configure agent executor with exploratory max turns
            if hasattr(agent_executor, "max_turns"):
                agent_executor.max_turns = self.criteria.max_turns

            if hasattr(agent_executor, "run"):
                target_url = str(request.base_url or "http://localhost:3000")
                outcome = await agent_executor.run(
                    browser=browser,
                    objective=objective,
                    target_url=target_url,
                )
                if outcome:
                    # Check if outcome discovered unexpected behaviors or defects
                    outcome_status = getattr(outcome, "status", "")
                    outcome_reason = getattr(outcome, "reason", "")
                    if outcome_status in ("FAILED", "BLOCKED", "DEFECT") or getattr(outcome, "failure_category", None) or "defect" in outcome_reason.lower() or "unexpected" in outcome_reason.lower():
                        defects.append({
                            "type": "agent_reported_defect",
                            "status": outcome_status,
                            "reason": outcome_reason,
                            "verification": getattr(outcome, "verification", {}),
                        })
                    if hasattr(outcome, "discoveries") and isinstance(outcome.discoveries, int):
                        for _ in range(max(0, outcome.discoveries - len(defects))):
                            defects.append({"type": "agent_discovery"})

        # 2. Emit defect_discovered events for any discovered defects
        discovery_count = len(defects)
        for defect in defects:
            payload = {
                "flow_id": str(target_flow_id),
                "feature": feature_name,
                "defect": defect,
            }
            if event_emitter:
                try:
                    res = event_emitter("defect_discovered", payload)
                    if hasattr(res, "__await__"):
                        await res
                except Exception:
                    pass

        # 3. For exploratory mode, discovering defects is a SUCCESS
        # Even if 0 defects found, exploratory run completed successfully without errors
        overall_status = "passed"
        flow_status = "passed"
        evidence_summary = {
            "mode": "exploratory",
            "objective": objective,
            "max_turns": self.criteria.max_turns,
            "discoveries": discovery_count,
            "defects": defects,
        }

        duration_ms = max(0, int((time.monotonic() - start_mono) * 1000))
        finished_at = datetime.now(timezone.utc)

        results = [
            FlowValidationResult(
                flow_id=uuid.UUID(str(target_flow_id)) if _is_valid_uuid(target_flow_id) else uuid.uuid4(),
                flow_name=target_flow_name,
                role="target",
                status=flow_status,
                duration_ms=duration_ms,
                state_changes={"discoveries": discovery_count},
            )
        ]

        return ValidationReport(
            request=request,
            impact_report=impact_report or ImpactReport(),
            results=results,
            overall_status=overall_status,
            discoveries=discovery_count,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            evidence_summary=evidence_summary,
        )


def _is_valid_uuid(val: Any) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError):
        return False
