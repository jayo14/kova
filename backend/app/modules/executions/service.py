"""Execution service for business logic."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.event_service import EventService
from app.modules.executions.models import ExecutionStatus
from app.modules.executions.repository import ExecutionEventRepository, ExecutionRepository
from app.modules.executions.schemas import ExecutionCreate


class ExecutionService:
    def __init__(self, db: AsyncSession):
        self.repo = ExecutionRepository(db)
        self.event_repo = ExecutionEventRepository(db)
        self.event_service = EventService(db)

    async def create_execution(self, data: ExecutionCreate):
        """Create a new execution record."""
        execution = await self.repo.create(flow_id=data.flow_id)
        await self.event_service.record_execution_created(execution.id)
        return execution

    async def get_execution(self, execution_id: uuid.UUID):
        """Get execution by ID."""
        return await self.repo.get_by_id(execution_id)

    async def list_executions(self, flow_id: uuid.UUID, skip: int = 0, limit: int = 100):
        """List executions for a flow."""
        return await self.repo.list_by_flow(flow_id, skip=skip, limit=limit)

    async def list_all(self, skip: int = 0, limit: int = 100):
        """List all executions."""
        return await self.repo.list_all(skip=skip, limit=limit)

    async def cancel_execution(self, execution_id: uuid.UUID):
        """Cancel an execution.

        Updates status to CANCELLED and records event.
        """
        await self.repo.update_status(execution_id, ExecutionStatus.CANCELLED)
        await self.event_service.record_execution_cancelled(execution_id)

    async def get_events(self, execution_id: uuid.UUID, skip: int = 0, limit: int = 1000):
        """Get events for an execution."""
        return await self.event_repo.list_by_execution(execution_id, skip=skip, limit=limit)
