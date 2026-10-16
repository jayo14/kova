from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.modules.auth.audit_log import AuditLogger
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.rbac import verify_project_role
from app.modules.auth.token_scopes import SCOPE_ORG_MANAGE, require_scope
from app.modules.organizations.models import AuditEvent, Organization
from app.modules.organizations.repository import OrganizationRepository
from app.modules.organizations.schemas import (
    AuditEventRead,
    OrganizationCreate,
    OrganizationMemberInvite,
    OrganizationMemberRead,
    OrganizationQuotaRead,
    OrganizationRead,
    ProjectMemberAdd,
    ProjectMemberRead,
)
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

router = APIRouter(prefix="/orgs", tags=["organizations"])
project_members_router = APIRouter(prefix="/projects", tags=["project-members"])


async def _require_org_role(
    org_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: str = "member",
) -> Organization:
    repo = OrganizationRepository(db)
    org = await repo.get_by_id(org_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
        )
    if org.owner_user_id == user.id:
        return org

    member = await repo.get_member(org_id, user.id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to organization"
        )
    if min_role in ("admin", "owner") and member.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Organization admin permissions required"
        )
    return org


@router.get("/me", response_model=OrganizationRead)
async def get_my_org(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    repo = OrganizationRepository(db)
    org = await repo.get_user_primary_org(user.id)
    return org


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_org(
    org_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    org = await _require_org_role(org_id, user, db, min_role="member")
    return org


@router.get("/{org_id}/members", response_model=list[OrganizationMemberRead])
async def list_org_members(
    org_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _require_org_role(org_id, user, db, min_role="member")
    repo = OrganizationRepository(db)
    members = await repo.list_members(org_id)
    out = []
    for m in members:
        out.append(
            OrganizationMemberRead(
                id=m.id,
                org_id=m.org_id,
                user_id=m.user_id,
                role=m.role,
                email=m.user.email if m.user else None,
                name=m.user.name if m.user else None,
                created_at=m.created_at,
            )
        )
    return out


@router.post("/{org_id}/members", response_model=OrganizationMemberRead, status_code=status.HTTP_201_CREATED)
async def invite_org_member(
    org_id: uuid.UUID,
    data: OrganizationMemberInvite,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _require_org_role(org_id, user, db, min_role="admin")
    user_repo = UserRepository(db)
    target_user = await user_repo.get_by_email(data.email)
    if not target_user:
        target_user = await user_repo.get_or_create(uuid.uuid4(), email=data.email, name=data.email.split("@")[0])

    repo = OrganizationRepository(db)
    existing = await repo.get_member(org_id, target_user.id)
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member of this organization")

    member = await repo.add_member(org_id, target_user.id, role=data.role)
    audit = AuditLogger(db)
    await audit.record(
        event_type="organization.member_invited",
        actor_user_id=user.id,
        org_id=org_id,
        action="invite_member",
        target=str(target_user.id),
        metadata={"email": data.email, "role": data.role},
    )

    return OrganizationMemberRead(
        id=member.id,
        org_id=member.org_id,
        user_id=member.user_id,
        role=member.role,
        email=target_user.email,
        name=target_user.name,
        created_at=member.created_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_org_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    org = await _require_org_role(org_id, user, db, min_role="admin")
    if org.owner_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot remove organization owner")

    repo = OrganizationRepository(db)
    success = await repo.remove_member(org_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")

    audit = AuditLogger(db)
    await audit.record(
        event_type="organization.member_removed",
        actor_user_id=user.id,
        org_id=org_id,
        action="remove_member",
        target=str(user_id),
    )


@router.get("/{org_id}/audit", response_model=list[AuditEventRead])
async def get_org_audit_log(
    org_id: uuid.UUID,
    from_date: Optional[datetime] = Query(None, alias="from"),
    to_date: Optional[datetime] = Query(None, alias="to"),
    actor: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve organization audit trail (org admin or owner only)."""
    await _require_org_role(org_id, user, db, min_role="admin")
    repo = OrganizationRepository(db)
    events = await repo.query_audit_events(
        org_id=org_id,
        from_date=from_date,
        to_date=to_date,
        actor_user_id=actor,
        action=action,
        limit=limit,
        skip=skip,
    )
    return [
        AuditEventRead(
            id=e.id,
            org_id=e.org_id,
            actor_user_id=e.actor_user_id,
            project_id=e.project_id,
            event_type=e.event_type,
            action=e.action,
            target=e.target,
            metadata=e.metadata_ or {},
            created_at=e.created_at,
        )
        for e in events
    ]


# ── Project Members Sub-Routes ─────────────────────────────


@project_members_router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
async def list_project_members(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await verify_project_role(db, project_id, user, min_role="viewer")
    repo = OrganizationRepository(db)
    members = await repo.list_project_members(project_id)
    return [
        ProjectMemberRead(
            id=m.id,
            project_id=m.project_id,
            user_id=m.user_id,
            role=m.role,
            email=m.user.email if m.user else None,
            name=m.user.name if m.user else None,
            created_at=m.created_at,
        )
        for m in members
    ]


@project_members_router.post(
    "/{project_id}/members", response_model=ProjectMemberRead, status_code=status.HTTP_201_CREATED
)
async def add_project_member(
    project_id: uuid.UUID,
    data: ProjectMemberAdd,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    project = await verify_project_role(db, project_id, user, min_role="admin")
    user_repo = UserRepository(db)
    target_user = None
    if data.user_id:
        target_user = await user_repo.get_by_id(data.user_id)
    elif data.email:
        target_user = await user_repo.get_by_email(data.email)
        if not target_user:
            target_user = await user_repo.get_or_create(uuid.uuid4(), email=data.email, name=data.email.split("@")[0])

    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    repo = OrganizationRepository(db)
    pm = await repo.add_project_member(project_id, target_user.id, role=data.role)

    if project.org_id:
        audit = AuditLogger(db)
        await audit.record(
            event_type="project.member_added",
            actor_user_id=user.id,
            org_id=project.org_id,
            project_id=project.id,
            action="add_project_member",
            target=str(target_user.id),
            metadata={"role": data.role, "email": target_user.email},
        )

    return ProjectMemberRead(
        id=pm.id,
        project_id=pm.project_id,
        user_id=pm.user_id,
        role=pm.role,
        email=target_user.email,
        name=target_user.name,
        created_at=pm.created_at,
    )


@project_members_router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    project = await verify_project_role(db, project_id, user, min_role="admin")
    if project.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot remove project owner from project")

    repo = OrganizationRepository(db)
    success = await repo.remove_project_member(project_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project member not found")

    if project.org_id:
        audit = AuditLogger(db)
        await audit.record(
            event_type="project.member_removed",
            actor_user_id=user.id,
            org_id=project.org_id,
            project_id=project.id,
            action="remove_project_member",
            target=str(user_id),
        )
