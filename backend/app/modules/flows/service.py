from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.repository import FlowRepository
from app.modules.flows.schemas import FlowCreate, FlowUpdate

if TYPE_CHECKING:
    from app.modules.flows.generator import GenerationRequest, GenerationResult


class FlowService:
    def __init__(self, db: AsyncSession):
        self.repo = FlowRepository(db)

    async def create_from_mission(
        self,
        project_id: uuid.UUID,
        mission: dict | Any,
        user_id: uuid.UUID,
        activate_immediately: bool = False,
        name: str | None = None,
    ):
        if hasattr(mission, "model_dump"):
            m_dict = mission.model_dump()
        elif isinstance(mission, dict):
            m_dict = mission
        else:
            m_dict = dict(mission)

        flow_name = name or m_dict.get("title") or m_dict.get("name") or "Discovered Mission"
        objective = m_dict.get("objective") or m_dict.get("description") or flow_name
        description = m_dict.get("description") or m_dict.get("objective") or ""
        persona = m_dict.get("persona")
        if isinstance(persona, str):
            persona_dict = {"role": persona}
        elif isinstance(persona, dict):
            persona_dict = persona
        else:
            persona_dict = None

        raw_steps = m_dict.get("steps") or []
        steps = []
        for s in raw_steps:
            if hasattr(s, "to_runner_dict"):
                steps.append(s.to_runner_dict())
            elif hasattr(s, "model_dump"):
                steps.append(s.model_dump())
            elif isinstance(s, dict):
                step_copy = dict(s)
                if "action" not in step_copy and "type" in step_copy:
                    step_copy["action"] = step_copy["type"]
                if "step_id" not in step_copy:
                    step_copy["step_id"] = step_copy.get("id") or uuid.uuid4().hex
                if "selector" not in step_copy and "target" in step_copy:
                    step_copy["selector"] = step_copy["target"]
                steps.append(step_copy)
            else:
                steps.append({"step_id": uuid.uuid4().hex, "action": "wait", "value": "1000"})

        raw_sc = m_dict.get("success_condition") or m_dict.get("successCondition")
        if isinstance(raw_sc, dict):
            success_condition = raw_sc
        elif isinstance(raw_sc, str):
            success_condition = {"description": raw_sc}
        else:
            success_condition = None

        routes: list[str] = []
        if m_dict.get("route_analysis") and isinstance(m_dict["route_analysis"], dict):
            p = m_dict["route_analysis"].get("path")
            if p:
                routes.append(p)
        if not routes:
            for s in steps:
                if isinstance(s, dict) and s.get("action") == "navigate":
                    u = s.get("url") or s.get("value")
                    if u and u not in routes:
                        routes.append(str(u))

        category = m_dict.get("category")
        confidence = float(m_dict.get("confidence") or 1.0)

        return await self.repo.create(
            project_id=project_id,
            name=flow_name,
            description=description,
            persona=persona_dict,
            objective=objective,
            steps=steps,
            success_condition=success_condition,
            routes=routes,
            capability=category,
            source="user_provided",
            confidence=confidence,
            active=activate_immediately,
            status="active",
        )

    async def create_flow(self, data: FlowCreate):
        return await self.repo.create(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            persona=data.persona,
            objective=data.objective,
            steps=[s.model_dump() for s in data.steps],
            success_condition=data.success_condition,
            preconditions=data.preconditions,
            dependencies=[d.model_dump() for d in data.dependencies],
            provides_capabilities=data.provides_capabilities,
            repeatability=data.repeatability,
            reset_strategy=data.reset_strategy,
            status=data.status,
            capability=data.capability,
            routes=data.routes,
            criticality=data.criticality,
            state_contract=data.state_contract.model_dump() if data.state_contract else None,
            goal_id=data.goal_id,
            persona_id=data.persona_id,
            page_ids=data.page_ids,
            active=data.active,
        )

    async def get_flow(self, flow_id: uuid.UUID):
        return await self.repo.get_by_id(flow_id)

    async def list_flows(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100):
        return await self.repo.list_by_project(project_id, skip=skip, limit=limit)

    async def update_flow(self, flow_id: uuid.UUID, data: FlowUpdate):
        steps = [s.model_dump() for s in data.steps] if data.steps is not None else None
        return await self.repo.update(
            flow_id,
            name=data.name,
            description=data.description,
            persona=data.persona,
            objective=data.objective,
            steps=steps,
            success_condition=data.success_condition,
            preconditions=data.preconditions,
            dependencies=[d.model_dump() for d in data.dependencies] if data.dependencies is not None else None,
            provides_capabilities=data.provides_capabilities,
            repeatability=data.repeatability,
            reset_strategy=data.reset_strategy,
            status=data.status,
            capability=data.capability,
            routes=data.routes,
            criticality=data.criticality,
            state_contract=data.state_contract.model_dump() if data.state_contract is not None else None,
            goal_id=data.goal_id,
            persona_id=data.persona_id,
            page_ids=data.page_ids,
            active=data.active,
        )

    async def delete_flow(self, flow_id: uuid.UUID):
        return await self.repo.delete(flow_id)

    async def generate_flows(
        self,
        project_id: uuid.UUID,
        request: "GenerationRequest | None" = None,
        goal_id: uuid.UUID | None = None,
        target_capability: str | None = None,
    ) -> "GenerationResult":
        from app.engine.ai.settings import ai_settings
        from app.modules.flows.generator import (
            AIFlowProposer,
            DeterministicFlowGenerator,
            GenerationRequest,
            GenerationResult,
        )

        if request is None:
            request = GenerationRequest(
                project_id=project_id,
                goal_id=goal_id,
                target_capability=target_capability,
            )

        det_gen = DeterministicFlowGenerator(self.repo.db)
        flows, unresolved = await det_gen.generate(request)

        ai_proposals = []
        if unresolved and ai_settings.ai_enabled:
            ai_proposer = AIFlowProposer(self.repo.db)
            proposed_flows, proposals = await ai_proposer.propose(project_id, unresolved)
            flows.extend(proposed_flows)
            ai_proposals.extend(proposals)

        # Persist generated flows with active=False (requiring review before CI).
        # Skip flows with zero steps (possible via AI proposals) so broken
        # FLOW_NOT_RUNNABLE shells are never persisted.
        persisted_flows = []
        for f in flows:
            if not f.internal:
                continue
            p_flow = await self.repo.create(
                project_id=project_id,
                name=f.name,
                goal_id=f.goal_id,
                persona_id=f.persona_id,
                page_ids=[str(p) for p in f.page_ids],
                steps=[s.to_runner_dict() for s in f.internal],
                state_contract=f.state_contract.model_dump() if f.state_contract else None,
                source=f.source,
                confidence=f.confidence,
                active=False,
                json_repr=f.json_repr,
                gherkin_repr=f.gherkin,
            )
            f.id = p_flow.id
            persisted_flows.append(f)
        flows = persisted_flows

        remaining_unresolved = (
            unresolved
            if not ai_proposals
            else [u for u in unresolved if not any(u in p.input_summary for p in ai_proposals)]
        )

        return GenerationResult(
            flows=flows,
            unresolved_goals=remaining_unresolved,
            ai_proposals=ai_proposals,
        )

    async def evaluate_stale_flows(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Re-evaluate all stale flows in a project against the current Product Graph."""
        from app.engine.ai.provider import get_ai_provider
        from app.engine.ai.reasoner import AgentReasoner
        from app.engine.ai.test_maintainer import TestMaintainer
        from app.modules.product_graph.repository import ProductGraphRepository

        reasoner = AgentReasoner(get_ai_provider())
        pg_repo = ProductGraphRepository(self.repo.db)
        maintainer = TestMaintainer(reasoner=reasoner, pg_repo=pg_repo, flow_repo=self.repo)

        flows = await self.repo.list_by_project(project_id)
        assessments = []
        still_valid = 0
        requires_review = 0

        for f in flows:
            assessment = await maintainer.evaluate_stale_flow(f.id)
            assessments.append(assessment.model_dump())
            if assessment.is_still_valid:
                still_valid += 1
            if assessment.requires_review:
                requires_review += 1

        return {
            "evaluated": len(assessments),
            "still_valid": still_valid,
            "requires_review": requires_review,
            "assessments": assessments,
        }


