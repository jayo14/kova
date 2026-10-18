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
        product_goal: str | None = None,
        env_config: dict | None = None,
        execution_limits: dict | None = None,
        safety_restrictions: dict | None = None,
        browser_settings: dict | None = None,
        test_credentials_ref: uuid.UUID | None = None,
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

        # Look up or create user's primary organization
        from app.modules.organizations.repository import OrganizationRepository
        org_repo = OrganizationRepository(self.db)
        org = await org_repo.get_user_primary_org(user_id)

        project = Project(
            user_id=user_id,
            org_id=org.id if org else None,
            name=name,
            base_url=base_url,
            description=description,
            product_goal=product_goal,
            env_config=env_config or {},
            execution_limits=execution_limits or {},
            safety_restrictions=safety_restrictions or {},
            browser_settings=browser_settings or {},
            test_credentials_ref=test_credentials_ref,
        )
        self.db.add(project)
        await self.db.flush()

        # Add project owner as admin project member
        from app.modules.organizations.models import ProjectMember
        pm = ProjectMember(
            id=uuid.uuid4(),
            project_id=project.id,
            user_id=user_id,
            role="admin",
        )
        self.db.add(pm)
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
        project = await self.get_by_id(project_id)
        if not project:
            return None
        if project.user_id == user_id:
            return project

        from app.modules.organizations.models import ProjectMember, OrganizationMember
        # Check project membership
        pm_res = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if pm_res.scalar_one_or_none():
            return project

        # Check organization membership
        if project.org_id:
            om_res = await self.db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.org_id == project.org_id,
                    OrganizationMember.user_id == user_id,
                )
            )
            if om_res.scalar_one_or_none():
                return project

        return None

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[Project]:
        result = await self.db.execute(
            select(Project).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_user(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Project]:
        from app.modules.organizations.models import ProjectMember, OrganizationMember
        stmt = (
            select(Project)
            .where(
                (Project.user_id == user_id)
                | Project.id.in_(
                    select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
                )
                | (
                    (Project.org_id.isnot(None))
                    & Project.org_id.in_(
                        select(OrganizationMember.org_id).where(OrganizationMember.user_id == user_id)
                    )
                )
            )
            .distinct()
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        name: str | None = None,
        description: str | None = None,
        base_url: str | None = None,
        product_goal: str | None = None,
        env_config: dict | None = None,
        execution_limits: dict | None = None,
        safety_restrictions: dict | None = None,
        browser_settings: dict | None = None,
        test_credentials_ref: uuid.UUID | None = None,
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
        if product_goal is not None:
            project.product_goal = product_goal
        if env_config is not None:
            project.env_config = env_config
        if execution_limits is not None:
            project.execution_limits = execution_limits
        if safety_restrictions is not None:
            project.safety_restrictions = safety_restrictions
        if browser_settings is not None:
            project.browser_settings = browser_settings
        if test_credentials_ref is not None:
            project.test_credentials_ref = test_credentials_ref
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
        try:
            from app.modules.validation.models import ProductModel, ValidationRun
            await self.db.execute(
                delete(ProductModel).where(ProductModel.project_id == project_id)
            )
            await self.db.execute(
                delete(ValidationRun).where(ValidationRun.project_id == project_id)
            )
        except Exception:
            pass
        await self.db.delete(project)
        await self.db.flush()
        return True

    async def get_product_model(self, project_id: uuid.UUID):
        try:
            from sqlalchemy import desc
            from app.modules.validation.models import ProductModel

            stmt = (
                select(ProductModel)
                .where(ProductModel.project_id == project_id)
                .order_by(desc(ProductModel.version))
                .limit(1)
            )
            res = await self.db.execute(stmt)
            return res.scalar_one_or_none()
        except Exception:
            return None
