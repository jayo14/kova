"""Credential API endpoints.

Manages credentials scoped to projects.
Passwords are never returned in read responses.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.credentials.schemas import CredentialCreate, CredentialRead
from app.modules.credentials.service import CredentialService
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["credentials"])


async def _verify_project_ownership(
    db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
):
    """Verify a project exists and belongs to the user."""
    project_repo = ProjectRepository(db)
    project = await project_repo.get_by_id_and_user(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post(
    "/{project_id}/credentials",
    response_model=CredentialRead,
    status_code=201,
)
async def create_credential(
    project_id: str,
    data: CredentialCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create a credential for a project."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")

    await _verify_project_ownership(db, pid, user.id)

    service = CredentialService(db)
    return await service.create_credential(pid, data)


@router.get(
    "/{project_id}/credentials",
    response_model=list[CredentialRead],
)
async def list_credentials(
    project_id: str,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List credentials for a project."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")

    await _verify_project_ownership(db, pid, user.id)

    service = CredentialService(db)
    return await service.list_credentials(pid, skip=skip, limit=limit)


@router.get(
    "/{project_id}/credentials/{credential_id}",
    response_model=CredentialRead,
)
async def get_credential(
    project_id: str,
    credential_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get a credential by ID."""
    try:
        pid = uuid.UUID(project_id)
        cid = uuid.UUID(credential_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ID")

    await _verify_project_ownership(db, pid, user.id)

    service = CredentialService(db)
    credential = await service.get_credential(cid)
    if credential is None or credential.project_id != pid:
        raise HTTPException(status_code=404, detail="Credential not found")
    return credential


@router.delete("/{project_id}/credentials/{credential_id}", status_code=204)
async def delete_credential(
    project_id: str,
    credential_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Delete a credential."""
    try:
        pid = uuid.UUID(project_id)
        cid = uuid.UUID(credential_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid ID")

    await _verify_project_ownership(db, pid, user.id)

    service = CredentialService(db)
    credential = await service.get_credential(cid)
    if credential is None or credential.project_id != pid:
        raise HTTPException(status_code=404, detail="Credential not found")

    deleted = await service.delete_credential(cid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
