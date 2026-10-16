import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.repository import FlowRepository
from app.modules.flows.schemas import FlowCreate, FlowUpdate


class FlowService:
    def __init__(self, db: AsyncSession):
        self.repo = FlowRepository(db)

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

        # Persist generated flows with active=False (requiring review before CI)
        for f in flows:
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

