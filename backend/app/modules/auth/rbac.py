from __future__ import annotations

import logging
import uuid
from typing import Callable, Literal, Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.organizations.models import OrganizationMember, ProjectMember
from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)

ROLE_LEVELS = {
    "viewer": 1,
    "tester": 2,
    "admin": 3,
}


async def get_user_project_role(
    db: AsyncSession,
    project: Project,
    user_id: uuid.UUID,
) -> str | None:
    """Determine a user's effective role on a project."""
    # 1. Project Owner is always admin
    if project.user_id == user_id:
        return "admin"

    # 2. Check direct project membership
    stmt = select(ProjectMember).where(
        ProjectMember.project_id == project.id,
        ProjectMember.user_id == user_id,
    )
    res = await db.execute(stmt)
    pm = res.scalar_one_or_none()
    if pm:
        return pm.role

    # 3. Check organization role if project belongs to an organization
    if project.org_id:
        org_stmt = select(OrganizationMember).where(
            OrganizationMember.org_id == project.org_id,
            OrganizationMember.user_id == user_id,
        )
        org_res = await db.execute(org_stmt)
        om = org_res.scalar_one_or_none()
        if om and om.role in ("owner", "admin"):
            return "admin"

    return None


async def verify_project_role(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    min_role: Literal["viewer", "tester", "admin"] = "viewer",
) -> Project:
    """Verify that user has at least min_role on project_id, returning the project."""
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Multi-tenant isolation: if project belongs to an org, verify user belongs to that org
    if project.org_id:
        org_stmt = select(OrganizationMember).where(
            OrganizationMember.org_id == project.org_id,
            OrganizationMember.user_id == user.id,
        )
        org_res = await db.execute(org_stmt)
        if not org_res.scalar_one_or_none() and project.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to organization project",
            )

    role = await get_user_project_role(db, project, user.id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: User is not a member of this project",
        )

    required_level = ROLE_LEVELS.get(min_role, 1)
    actual_level = ROLE_LEVELS.get(role, 0)
    if actual_level < required_level:
        logger.warning(
            "User %s has role '%s' on project %s, but '%s' is required",
            user.id,
            role,
            project.id,
            min_role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Insufficient project role '{role}', requires '{min_role}'",
        )

    return project


def require_project_role(min_role: Literal["viewer", "tester", "admin"]) -> Callable:
    """FastAPI dependency for endpoints with {project_id} in path."""
    async def _dependency(
        project_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_session),
    ) -> Project:
        try:
            proj_uuid = uuid.UUID(str(project_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid project ID",
            )
        return await verify_project_role(db, proj_uuid, user, min_role)

    return _dependency
