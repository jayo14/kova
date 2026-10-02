import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.projects.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.modules.projects.service import ProjectService
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    return await service.create_project(data, user_id=user.id)


@router.get("/", response_model=list[ProjectRead])
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    return await service.list_projects(user_id=user.id, skip=skip, limit=limit)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    try:
        project = await service.get_project(uuid.UUID(project_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    try:
        project = await service.update_project(uuid.UUID(project_id), user.id, data)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    try:
        deleted = await service.delete_project(uuid.UUID(project_id), user.id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
