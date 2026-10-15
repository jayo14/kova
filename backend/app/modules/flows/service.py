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
        )

    async def delete_flow(self, flow_id: uuid.UUID):
        return await self.repo.delete(flow_id)
