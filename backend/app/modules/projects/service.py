import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.repo = ProjectRepository(db)

    async def create_project(self, data: ProjectCreate, user_id: uuid.UUID):
        return await self.repo.create(
            user_id=user_id, name=data.name, base_url=data.base_url, description=data.description
        )

    async def get_project(self, project_id: uuid.UUID, user_id: uuid.UUID):
        return await self.repo.get_by_id_and_user(project_id, user_id)

    async def list_projects(self, user_id: uuid.UUID, skip: int = 0, limit: int = 100):
        return await self.repo.list_by_user(user_id, skip=skip, limit=limit)

    async def update_project(self, project_id: uuid.UUID, user_id: uuid.UUID, data: ProjectUpdate):
        return await self.repo.update(
            project_id,
            user_id=user_id,
            name=data.name,
            description=data.description,
            base_url=data.base_url,
        )

    async def delete_project(self, project_id: uuid.UUID, user_id: uuid.UUID):
        return await self.repo.delete(project_id, user_id)
