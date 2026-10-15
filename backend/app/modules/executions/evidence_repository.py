import uuid
from typing import Any

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
        purpose: str = "legacy",
        step_id: str | None = None,
        description: str | None = None,
        status: str = "CAPTURED",
        storage_key: str | None = None,
        mime_type: str | None = None,
        metadata: dict | None = None,
        dom_snapshot: str | None = None,
        a11y_tree: str | None = None,
        network_log: list | dict | None = None,
        video_url: str | None = None,
        trace_url: str | None = None,
        element_locator: str | None = None,
        timestamp_range: list | None = None,
        note: str | None = None,
    ) -> Evidence:
        evidence = Evidence(
            execution_id=execution_id,
            type=type,
            title=title,
            purpose=purpose,
            step_id=step_id,
            description=description,
            status=status,
            storage_key=storage_key,
            mime_type=mime_type,
            extra_data=metadata or {},
            dom_snapshot=dom_snapshot,
            a11y_tree=a11y_tree,
            network_log=network_log,
            video_url=video_url,
            trace_url=trace_url,
            element_locator=element_locator,
            timestamp_range=timestamp_range,
            note=note,
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

    async def attach_execution_artifacts(
        self,
        execution_id: uuid.UUID,
        video_url: str | None = None,
        trace_url: str | None = None,
    ) -> int:
        """Update all evidence records for an execution with video_url and/or trace_url."""
        from sqlalchemy import update

        values: dict[str, Any] = {}
        if video_url is not None:
            values["video_url"] = video_url
        if trace_url is not None:
            values["trace_url"] = trace_url
        if not values:
            return 0

        result = await self.db.execute(
            update(Evidence)
            .where(Evidence.execution_id == execution_id)
            .values(**values)
        )
        await self.db.flush()
        return result.rowcount
