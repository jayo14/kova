import uuid

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project


class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID | None = None,
        name: str = "",
        base_url: str = "",
        description: str | None = None,
    ) -> Project:
        if user_id is None:
            from app.modules.users.models import User

            result = await self.db.execute(select(User).limit(1))
            default_user = result.scalar_one_or_none()
            if default_user is None:
                default_user = User(
                    id=uuid.uuid4(),
                    email="system@kova.local",
                    name="System User",
                )
                self.db.add(default_user)
                await self.db.flush()
            user_id = default_user.id

        project = Project(
            user_id=user_id, name=name, base_url=base_url, description=description
        )
        self.db.add(project)
        await self.db.flush()
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> Project | None:
        result = await self.db.execute(
            select(Project).where(
                Project.id == project_id, Project.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[Project]:
        result = await self.db.execute(
            select(Project).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_user(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Project]:
        result = await self.db.execute(
            select(Project)
            .where(Project.user_id == user_id)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        name: str | None = None,
        description: str | None = None,
        base_url: str | None = None,
    ) -> Project | None:
        if user_id is not None:
            project = await self.get_by_id_and_user(project_id, user_id)
        else:
            project = await self.get_by_id(project_id)
        if project is None:
            return None
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if base_url is not None:
            project.base_url = base_url
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def delete(
        self, project_id: uuid.UUID, user_id: uuid.UUID | None = None
    ) -> bool:
        if user_id is not None:
            project = await self.get_by_id_and_user(project_id, user_id)
        else:
            project = await self.get_by_id(project_id)
        if project is None:
            return False
        # Explicitly delete children first (FK is NOT NULL, can't rely on cascade nulling)
        from app.modules.credentials.models import Credential
        from app.modules.flows.models import Flow
        await self.db.execute(
            delete(Credential).where(Credential.project_id == project_id)
        )
        await self.db.execute(
            delete(Flow).where(Flow.project_id == project_id)
        )
        await self.db.delete(project)
        await self.db.flush()
        return True
