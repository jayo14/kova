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

    async def create_demo_project(
        self, user_id: uuid.UUID, base_url: str = "http://127.0.0.1:8090"
    ):
        project = await self.repo.create(
            user_id=user_id,
            name="Buggy Demo App",
            base_url=base_url,
            description="Pre-configured demo application showcasing Kova detecting planted UI and network bugs.",
        )
        from app.modules.flows.repository import FlowRepository
        flow_repo = FlowRepository(self.repo.db)
        # Bug 1: Contact form network 500 error
        await flow_repo.create(
            project_id=project.id,
            name="Contact Form Submission",
            description="Submit contact form and expect confirmation without network errors",
            steps=[
                {"type": "navigate", "url": f"{base_url}/contact"},
                {"type": "wait", "value": "500"},
                {"type": "type", "target": "input[name='name']", "value": "Demo User"},
                {"type": "type", "target": "input[name='email']", "value": "user@example.com"},
                {"type": "type", "target": "textarea[name='message']", "value": "Testing buggy demo app contact form"},
                {"type": "click", "target": "button[type='submit']"},
                {"type": "wait", "value": "1500"},
            ],
            success_condition={"text_visible": "Thank"},
        )
        # Bug 2: Broken login flow (fails verification)
        await flow_repo.create(
            project_id=project.id,
            name="User Authentication",
            description="Attempt user login and verify transition away from login page",
            steps=[
                {"type": "navigate", "url": f"{base_url}/login"},
                {"type": "wait", "value": "500"},
                {"type": "type", "target": "input[name='email']", "value": "user@example.com"},
                {"type": "type", "target": "input[name='password']", "value": "SecurePass123!"},
                {"type": "click", "target": "button[type='submit']"},
                {"type": "wait", "value": "1500"},
            ],
            success_condition={"auth_verified": {"auth_path": "/login"}},
        )
        return project

