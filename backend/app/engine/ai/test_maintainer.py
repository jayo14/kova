"""AI Test Maintainer (§5 capability F + §4 Stage 8).

When interface drift occurs, determines whether an existing locator or step can be
updated without weakening the original acceptance criteria. Never blindly rewrites
or weakens test criteria. Material changes require human sign-off.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import ScenarioValidityAssessment
from app.modules.flows.repository import FlowRepository
from app.modules.product_graph.repository import ProductGraphRepository

logger = logging.getLogger(__name__)


class TestMaintainer:
    """Evaluates whether stale flows remain valid against updated application interfaces."""

    __test__ = False


    def __init__(
        self,
        reasoner: AgentReasoner,
        pg_repo: ProductGraphRepository | None = None,
        flow_repo: FlowRepository | None = None,
    ):
        self.reasoner = reasoner
        self.pg_repo = pg_repo
        self.flow_repo = flow_repo

    async def evaluate_stale_flow(
        self,
        flow_id: uuid.UUID,
        new_page_state: dict[str, Any] | None = None,
    ) -> ScenarioValidityAssessment:
        """Re-evaluate a single flow against current page/graph state."""
        if not self.flow_repo:
            raise ValueError("FlowRepository required for evaluate_stale_flow")

        flow = await self.flow_repo.get_by_id(flow_id)
        if not flow:
            raise ValueError(f"Flow {flow_id} not found")

        if new_page_state is None:
            if self.pg_repo:
                try:
                    pages = await self.pg_repo.get_pages(flow.project_id)
                    new_page_state = {
                        "url": pages[0].url if pages else "/",
                        "buttons": [],
                        "forms": [],
                        "locator_matches": [],
                    }
                except Exception:
                    new_page_state = {"url": "/", "buttons": [], "forms": [], "locator_matches": []}
            else:
                new_page_state = {"url": "/", "buttons": [], "forms": [], "locator_matches": []}

        original_version = getattr(flow, "last_validated_against_graph_version", None) or 0

        # AI assessment of scenario validity
        assessment = await self.reasoner.evaluate_scenario_validity(
            flow={
                "id": str(flow.id),
                "objective": getattr(flow, "objective", ""),
                "success_condition": getattr(flow, "success_condition", {}),
                "steps": getattr(flow, "steps", []) or [],
            },
            new_page_state=new_page_state,
            original_graph_version=original_version,
        )

        current_version = original_version + 1
        if self.pg_repo and hasattr(self.pg_repo, "get_current_version"):
            try:
                current_version = await self.pg_repo.get_current_version(flow.project_id)
            except Exception:
                pass

        stale_reason = "; ".join(assessment.changes_detected) if assessment.changes_detected else None
        # Strict rule: NEVER modify flow.success_condition or steps. Only update metadata.
        await self.flow_repo.update(
            flow_id,
            {
                "stale_reason": stale_reason,
                "requires_review": assessment.requires_review,
                "last_validated_against_graph_version": current_version,
            },
        )

        return assessment
