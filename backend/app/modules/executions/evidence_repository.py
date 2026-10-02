import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.evidence_model import Evidence


class EvidenceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        execution_id: uuid.UUID,
        type: str,
        title: str,
        description: str | None = None,
        status: str = "CAPTURED",
        storage_key: str | None = None,
        mime_type: str | None = None,
        metadata: dict | None = None,
    ) -> Evidence:
        evidence = Evidence(
            execution_id=execution_id,
            type=type,
            title=title,
            description=description,
            status=status,
            storage_key=storage_key,
            mime_type=mime_type,
            metadata=metadata or {},
        )
        self.db.add(evidence)
        await self.db.flush()
        return evidence

    async def get_by_id(self, evidence_id: uuid.UUID) -> Evidence | None:
        result = await self.db.execute(
            select(Evidence).where(Evidence.id == evidence_id)
        )
        return result.scalar_one_or_none()

    async def list_by_execution(
        self, execution_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Evidence]:
        result = await self.db.execute(
            select(Evidence)
            .where(Evidence.execution_id == execution_id)
            .order_by(Evidence.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_by_execution(self, execution_id: uuid.UUID) -> int:
        """Delete all evidence records for an execution. Returns count deleted."""
        evidence_items = await self.list_by_execution(execution_id, limit=1000)
        count = len(evidence_items)
        for ev in evidence_items:
            await self.db.delete(ev)
        if count:
            await self.db.flush()
        return count
