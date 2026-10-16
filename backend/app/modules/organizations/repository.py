from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.organizations.crypto import generate_org_dek, wrap_dek
from app.modules.organizations.models import (
    AuditEvent,
    Organization,
    OrganizationMember,
    OrganizationQuota,
    ProjectMember,
)
from app.modules.users.models import User


PLAN_DEFAULTS = {
    "free": {
        "max_concurrent_executions": 2,
        "max_executions_per_day": 50,
        "max_product_graph_size": 100,
        "max_evidence_storage_mb": 100,
        "allowed_integrations": ["github"],
    },
    "pro": {
        "max_concurrent_executions": 5,
        "max_executions_per_day": 500,
        "max_product_graph_size": 1000,
        "max_evidence_storage_mb": 5000,
        "allowed_integrations": ["github", "gitlab"],
    },
    "enterprise": {
        "max_concurrent_executions": 20,
        "max_executions_per_day": 5000,
        "max_product_graph_size": 10000,
        "max_evidence_storage_mb": 50000,
        "allowed_integrations": ["*"],
    },
}


class OrganizationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_organization(
        self,
        name: str,
        owner_user_id: uuid.UUID,
        plan: str = "free",
        slug: Optional[str] = None,
    ) -> Organization:
        org_id = uuid.uuid4()
        if not slug:
            clean_name = "".join(c for c in name.lower() if c.isalnum() or c in ("-", "_")).strip()
            slug = f"{clean_name or 'org'}-{str(org_id)[:8]}"

        wrapped_dek = None
        if plan == "enterprise":
            raw_dek = generate_org_dek()
            wrapped_dek = wrap_dek(raw_dek)

        org = Organization(
            id=org_id,
            name=name,
            slug=slug,
            owner_user_id=owner_user_id,
            plan=plan,
            wrapped_dek=wrapped_dek,
        )
        self.db.add(org)

        # Create owner membership
        member = OrganizationMember(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=owner_user_id,
            role="owner",
        )
        self.db.add(member)

        # Create quota
        plan_cfg = PLAN_DEFAULTS.get(plan, PLAN_DEFAULTS["free"])
        quota = OrganizationQuota(
            id=uuid.uuid4(),
            org_id=org_id,
            max_concurrent_executions=plan_cfg["max_concurrent_executions"],
            max_executions_per_day=plan_cfg["max_executions_per_day"],
            max_product_graph_size=plan_cfg["max_product_graph_size"],
            max_evidence_storage_mb=plan_cfg["max_evidence_storage_mb"],
            allowed_integrations=plan_cfg["allowed_integrations"],
        )
        self.db.add(quota)

        await self.db.commit()
        await self.db.refresh(org)
        return org

    async def get_by_id(self, org_id: uuid.UUID) -> Optional[Organization]:
        stmt = (
            select(Organization)
            .where(Organization.id == org_id)
            .options(selectinload(Organization.quota), selectinload(Organization.members))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[Organization]:
        stmt = select(Organization).where(Organization.slug == slug)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_user_primary_org(self, user_id: uuid.UUID) -> Organization:
        """Fetch the user's primary organization, creating a default one if none exists."""
        stmt = (
            select(Organization)
            .join(OrganizationMember, OrganizationMember.org_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at.asc())
        )
        res = await self.db.execute(stmt)
        org = res.scalars().first()
        if org:
            return org

        # Create personal default organization
        u_stmt = select(User).where(User.id == user_id)
        u_res = await self.db.execute(u_stmt)
        user = u_res.scalar_one_or_none()
        org_name = f"{user.name or 'Personal'}'s Workspace" if user else "Personal Workspace"
        return await self.create_organization(name=org_name, owner_user_id=user_id, plan="free")

    async def add_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, role: str = "member"
    ) -> OrganizationMember:
        member = OrganizationMember(
            id=uuid.uuid4(),
            org_id=org_id,
            user_id=user_id,
            role=role,
        )
        self.db.add(member)
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def get_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[OrganizationMember]:
        stmt = select(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.user_id == user_id,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_members(self, org_id: uuid.UUID) -> list[OrganizationMember]:
        stmt = (
            select(OrganizationMember)
            .where(OrganizationMember.org_id == org_id)
            .options(selectinload(OrganizationMember.user))
            .order_by(OrganizationMember.created_at.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def remove_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.role != "owner",
        )
        res = await self.db.execute(stmt)
        await self.db.commit()
        return res.rowcount > 0

    async def get_quota(self, org_id: uuid.UUID) -> Optional[OrganizationQuota]:
        stmt = select(OrganizationQuota).where(OrganizationQuota.org_id == org_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def add_project_member(
        self, project_id: uuid.UUID, user_id: uuid.UUID, role: str = "viewer"
    ) -> ProjectMember:
        # Check if already exists
        stmt = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        res = await self.db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            existing.role = role
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        pm = ProjectMember(
            id=uuid.uuid4(),
            project_id=project_id,
            user_id=user_id,
            role=role,
        )
        self.db.add(pm)
        await self.db.commit()
        await self.db.refresh(pm)
        return pm

    async def list_project_members(self, project_id: uuid.UUID) -> list[ProjectMember]:
        stmt = (
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .options(selectinload(ProjectMember.user))
            .order_by(ProjectMember.created_at.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def remove_project_member(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        res = await self.db.execute(stmt)
        await self.db.commit()
        return res.rowcount > 0

    async def query_audit_events(
        self,
        org_id: uuid.UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        actor_user_id: Optional[uuid.UUID] = None,
        action: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent).where(AuditEvent.org_id == org_id)
        if from_date:
            stmt = stmt.where(AuditEvent.created_at >= from_date)
        if to_date:
            stmt = stmt.where(AuditEvent.created_at <= to_date)
        if actor_user_id:
            stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
        if action:
            stmt = stmt.where(AuditEvent.action == action)

        stmt = stmt.order_by(desc(AuditEvent.created_at)).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
