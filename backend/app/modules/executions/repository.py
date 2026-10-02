import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.event_model import ExecutionEvent
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.state_machine import validate_transition


class ExecutionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, flow_id: uuid.UUID) -> Execution:
        execution = Execution(flow_id=flow_id)
        self.db.add(execution)
        await self.db.flush()
        return execution

    async def get_by_id(self, execution_id: uuid.UUID) -> Execution | None:
        result = await self.db.execute(
            select(Execution).where(Execution.id == execution_id)
        )
        return result.scalar_one_or_none()

    async def list_by_flow(
        self, flow_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Execution]:
        result = await self.db.execute(
            select(Execution)
            .where(Execution.flow_id == flow_id)
            .order_by(Execution.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[Execution]:
        """List all executions."""
        result = await self.db.execute(
            select(Execution)
            .order_by(Execution.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        execution_id: uuid.UUID,
        status: ExecutionStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Execution:
        execution = await self.get_by_id(execution_id)
        if execution is None:
            raise ValueError(f"Execution {execution_id} not found")

        validate_transition(execution.status, status.value)

        execution.status = status.value
        now = datetime.now(timezone.utc)
        if status == ExecutionStatus.RUNNING and execution.started_at is None:
            execution.started_at = now
        if status in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMEOUT,
            ExecutionStatus.BLOCKED,
            ExecutionStatus.UNVERIFIED,
        ):
            execution.completed_at = now
        if error_code is not None:
            execution.error_code = error_code
        if error_message is not None:
            execution.error_message = error_message
        await self.db.flush()
        return execution


class ExecutionEventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        execution_id: uuid.UUID,
        event_type: str,
        payload: dict | None = None,
    ) -> ExecutionEvent:
        event = ExecutionEvent(
            execution_id=execution_id,
            event_type=event_type,
            payload=payload or {},
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_by_execution(
        self, execution_id: uuid.UUID, skip: int = 0, limit: int = 1000
    ) -> list[ExecutionEvent]:
        result = await self.db.execute(
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.created_at.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
