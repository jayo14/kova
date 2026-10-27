import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.suites.models import (
    SuiteRun,
    SuiteRunItem,
    TestSuite,
    TestSuiteVersion,
)


class SuiteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_suite(
        self,
        *,
        project_id: uuid.UUID,
        name: str,
        description: str | None,
        created_by: uuid.UUID | None,
    ) -> TestSuite:
        suite = TestSuite(
            project_id=project_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        self.db.add(suite)
        await self.db.flush()
        return suite

    async def get_suite(self, suite_id: uuid.UUID) -> TestSuite | None:
        result = await self.db.execute(select(TestSuite).where(TestSuite.id == suite_id))
        return result.scalar_one_or_none()

    async def list_suites(self, project_id: uuid.UUID) -> list[TestSuite]:
        result = await self.db.execute(
            select(TestSuite)
            .where(TestSuite.project_id == project_id)
            .order_by(TestSuite.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_suite(self, suite: TestSuite) -> None:
        await self.db.delete(suite)
        await self.db.flush()

    async def create_version(
        self,
        *,
        suite_id: uuid.UUID,
        version: int,
        flow_snapshot: list[dict],
        checksum: str,
        notes: str | None,
        created_by: uuid.UUID | None,
    ) -> TestSuiteVersion:
        record = TestSuiteVersion(
            suite_id=suite_id,
            version=version,
            flow_snapshot=flow_snapshot,
            checksum=checksum,
            notes=notes,
            created_by=created_by,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def get_version(self, suite_id: uuid.UUID, version: int) -> TestSuiteVersion | None:
        result = await self.db.execute(
            select(TestSuiteVersion).where(
                TestSuiteVersion.suite_id == suite_id,
                TestSuiteVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(self, suite_id: uuid.UUID) -> list[TestSuiteVersion]:
        result = await self.db.execute(
            select(TestSuiteVersion)
            .where(TestSuiteVersion.suite_id == suite_id)
            .order_by(TestSuiteVersion.version.desc())
        )
        return list(result.scalars().all())

    async def create_run(self, **values) -> SuiteRun:
        run = SuiteRun(**values)
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: uuid.UUID) -> SuiteRun | None:
        result = await self.db.execute(select(SuiteRun).where(SuiteRun.id == run_id))
        return result.scalar_one_or_none()

    async def list_runs(self, suite_id: uuid.UUID, limit: int = 50) -> list[SuiteRun]:
        result = await self.db.execute(
            select(SuiteRun)
            .where(SuiteRun.suite_id == suite_id)
            .order_by(SuiteRun.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_completed_runs(
        self,
        suite_id: uuid.UUID,
        *,
        limit: int = 5,
        exclude_run_id: uuid.UUID | None = None,
        suite_version: int | None = None,
    ) -> list[SuiteRun]:
        statement = select(SuiteRun).where(
            SuiteRun.suite_id == suite_id,
            SuiteRun.status.in_(["completed", "partial"]),
        )
        if exclude_run_id is not None:
            statement = statement.where(SuiteRun.id != exclude_run_id)
        if suite_version is not None:
            statement = statement.where(SuiteRun.suite_version == suite_version)
        statement = statement.order_by(SuiteRun.created_at.desc()).limit(limit)
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def add_item(self, **values) -> SuiteRunItem:
        item = SuiteRunItem(**values)
        self.db.add(item)
        await self.db.flush()
        return item

    async def list_items(self, run_id: uuid.UUID) -> list[SuiteRunItem]:
        result = await self.db.execute(
            select(SuiteRunItem)
            .where(SuiteRunItem.suite_run_id == run_id)
            .order_by(SuiteRunItem.position.asc(), SuiteRunItem.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_items_for_runs(self, run_ids: list[uuid.UUID]) -> list[SuiteRunItem]:
        if not run_ids:
            return []
        result = await self.db.execute(
            select(SuiteRunItem)
            .where(SuiteRunItem.suite_run_id.in_(run_ids))
            .order_by(SuiteRunItem.position.asc(), SuiteRunItem.created_at.asc())
        )
        return list(result.scalars().all())
