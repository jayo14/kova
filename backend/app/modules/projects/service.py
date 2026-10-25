import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.repo = ProjectRepository(db)

    async def _validate_create(self, data: ProjectCreate, user_id: uuid.UUID) -> None:
        if data.execution_limits:
            if data.execution_limits.max_duration_seconds < 30:
                raise ValueError("max_duration_seconds must be at least 30")
            if data.execution_limits.max_duration_seconds > 1800:
                raise ValueError("max_duration_seconds must be at most 1800 (30 min)")
            if data.execution_limits.max_agent_turns > 100:
                raise ValueError("max_agent_turns must be at most 100")
        if data.safety_restrictions and data.env_config:
            if data.safety_restrictions.production_access_allowed and data.env_config.target == "production":
                if not data.description or "I ACKNOWLEDGE production access" not in data.description:
                    raise ValueError("Production access requires explicit acknowledgment in description")
        if data.test_credentials_ref:
            from app.modules.credentials.repository import CredentialRepository
            cred_repo = CredentialRepository(self.repo.db)
            cred = await cred_repo.get_by_id(data.test_credentials_ref)
            if not cred:
                raise ValueError("test_credentials_ref must reference a credential owned by the user")
            if hasattr(cred, "user_id") and cred.user_id != user_id:
                raise ValueError("test_credentials_ref must reference a credential owned by the user")
            if hasattr(cred, "project") and cred.project and cred.project.user_id != user_id:
                raise ValueError("test_credentials_ref must reference a credential owned by the user")
            if hasattr(cred, "project_id"):
                owner_project = await self.repo.get_by_id(cred.project_id)
                if owner_project and owner_project.user_id != user_id:
                    raise ValueError("test_credentials_ref must reference a credential owned by the user")

    async def create_project(self, data: ProjectCreate, user_id: uuid.UUID):
        await self._validate_create(data, user_id)
        env_dict = data.env_config.model_dump() if data.env_config else {}
        if not env_dict.get("logo_url") and data.base_url:
            import re
            from urllib.parse import urlparse
            try:
                clean_host = re.sub(r"^www\d*\.", "", (urlparse(data.base_url).hostname or "").lower())
                if clean_host:
                    env_dict["logo_url"] = f"https://www.google.com/s2/favicons?domain={clean_host}&sz=128"
            except Exception:
                pass

        return await self.repo.create(
            user_id=user_id,
            name=data.name,
            base_url=data.base_url,
            description=data.description,
            product_goal=data.product_goal,
            env_config=env_dict,
            execution_limits=data.execution_limits.model_dump() if data.execution_limits else {},
            safety_restrictions=data.safety_restrictions.model_dump() if data.safety_restrictions else {},
            browser_settings=data.browser_settings.model_dump() if data.browser_settings else {},
            test_credentials_ref=data.test_credentials_ref,
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
            product_goal=data.product_goal,
            env_config=data.env_config.model_dump() if data.env_config is not None else None,
            execution_limits=data.execution_limits.model_dump() if data.execution_limits is not None else None,
            safety_restrictions=data.safety_restrictions.model_dump() if data.safety_restrictions is not None else None,
            browser_settings=data.browser_settings.model_dump() if data.browser_settings is not None else None,
            test_credentials_ref=data.test_credentials_ref,
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
                {"type": "textarea[name='message']", "target": "textarea[name='message']", "value": "Testing buggy demo app contact form"},
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
