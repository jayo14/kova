import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.models import Flow


class FlowRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str | None = None,
        persona: dict | None = None,
        objective: str | None = None,
        steps: list[dict] | None = None,
        success_condition: dict | None = None,
        preconditions: dict | None = None,
        dependencies: list[dict] | None = None,
        provides_capabilities: list[str] | None = None,
        repeatability: str = "repeatable",
        reset_strategy: str | None = None,
    ) -> Flow:
        flow = Flow(
            project_id=project_id,
            name=name,
            description=description,
            persona=persona,
            objective=objective,
            steps=steps or [],
            success_condition=success_condition,
            preconditions=preconditions,
            dependencies=dependencies or [],
            provides_capabilities=provides_capabilities or [],
            repeatability=repeatability,
            reset_strategy=reset_strategy,
        )
        self.db.add(flow)
        await self.db.flush()
        return flow

    async def get_by_id(self, flow_id: uuid.UUID) -> Flow | None:
        result = await self.db.execute(select(Flow).where(Flow.id == flow_id))
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Flow]:
        result = await self.db.execute(
            select(Flow)
            .where(Flow.project_id == project_id)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update(
        self,
        flow_id: uuid.UUID,
        name: str | None = None,
        description: str | None = None,
        persona: dict | None = None,
        objective: str | None = None,
        steps: list[dict] | None = None,
        success_condition: dict | None = None,
        preconditions: dict | None = None,
        dependencies: list[dict] | None = None,
        provides_capabilities: list[str] | None = None,
        repeatability: str | None = None,
        reset_strategy: str | None = None,
    ) -> Flow | None:
        flow = await self.get_by_id(flow_id)
        if flow is None:
            return None
        changed = any(value is not None for value in (name, description, persona, objective, steps, success_condition, preconditions, dependencies, provides_capabilities, repeatability, reset_strategy))
        if name is not None:
            flow.name = name
        if description is not None:
            flow.description = description
        if persona is not None:
            flow.persona = persona
        if objective is not None:
            flow.objective = objective
        if steps is not None:
            flow.steps = steps
        if success_condition is not None:
            flow.success_condition = success_condition
        if preconditions is not None:
            flow.preconditions = preconditions
        if dependencies is not None:
            flow.dependencies = dependencies
        if provides_capabilities is not None:
            flow.provides_capabilities = provides_capabilities
        if repeatability is not None:
            flow.repeatability = repeatability
        if reset_strategy is not None:
            flow.reset_strategy = reset_strategy
        if changed:
            flow.version += 1
        await self.db.flush()
        await self.db.refresh(flow)
        return flow

    async def delete(self, flow_id: uuid.UUID) -> bool:
        flow = await self.get_by_id(flow_id)
        if flow is None:
            return False
        await self.db.delete(flow)
        await self.db.flush()
        return True
