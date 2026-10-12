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


@router.post("/demo", response_model=ProjectRead, status_code=201)
async def create_demo_project_endpoint(
    base_url: str = "http://127.0.0.1:8090",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    return await service.create_demo_project(user_id=user.id, base_url=base_url)



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


from app.modules.validation.service import ValidationService
from app.modules.validation.schemas import ProductModelRead, ProductModelUpdate, ValidationRunRead


@router.get("/{project_id}/knowledge", response_model=ProductModelRead)
async def get_project_knowledge(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve the latest persistent product model and discovered capabilities."""
    service = ProjectService(db)
    project = await service.get_project(project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    val_service = ValidationService(db)
    return await val_service.get_latest_product_model(project_id)


@router.put("/{project_id}/knowledge", response_model=ProductModelRead)
async def update_project_knowledge(
    project_id: uuid.UUID,
    data: ProductModelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Update and version the persistent product model with newly discovered capabilities."""
    service = ProjectService(db)
    project = await service.get_project(project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    val_service = ValidationService(db)
    model = await val_service.update_product_model(project_id, data)
    await db.commit()
    await db.refresh(model)
    return model


@router.get("/{project_id}/validations", response_model=list[ValidationRunRead])
async def list_project_validations(
    project_id: uuid.UUID,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List historical continuous validation runs and baseline comparisons."""
    service = ProjectService(db)
    project = await service.get_project(project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    val_service = ValidationService(db)
    return await val_service.list_validation_runs(project_id, limit=limit)
