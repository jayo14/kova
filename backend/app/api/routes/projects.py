import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.projects.schemas import ProjectCreate, ProjectRead, ProjectUpdate
from app.modules.projects.service import ProjectService
from app.modules.users.models import User

router = APIRouter(prefix="/projects", tags=["projects"])


from app.modules.auth.audit_log import AuditLogger
from app.modules.auth.rbac import verify_project_role
from app.modules.auth.token_scopes import SCOPE_FLOWS_WRITE, require_scope
from app.modules.flows.schemas import FlowRead, FlowUpdate
from app.modules.flows.service import FlowService


@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    service = ProjectService(db)
    try:
        project = await service.create_project(data, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if project.org_id:
        audit = AuditLogger(db)
        await audit.record(
            event_type="project.created",
            actor_user_id=user.id,
            org_id=project.org_id,
            project_id=project.id,
            action="create_project",
            target=project.name,
            metadata={"base_url": project.base_url},
        )
    return project


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
    try:
        proj_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")
    project = await verify_project_role(db, proj_uuid, user, min_role="viewer")
    return project


@router.put("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    try:
        proj_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")

    await verify_project_role(db, proj_uuid, user, min_role="admin")
    service = ProjectService(db)
    project = await service.update_project(proj_uuid, user.id, data)
    if project and project.org_id:
        audit = AuditLogger(db)
        await audit.record(
            event_type="project.updated",
            actor_user_id=user.id,
            org_id=project.org_id,
            project_id=project.id,
            action="update_project",
            target=project.name,
        )
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    try:
        proj_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project ID")

    project = await verify_project_role(db, proj_uuid, user, min_role="admin")
    service = ProjectService(db)
    org_id = project.org_id
    deleted = await service.delete_project(proj_uuid, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    if org_id:
        audit = AuditLogger(db)
        await audit.record(
            event_type="project.deleted",
            actor_user_id=user.id,
            org_id=org_id,
            project_id=None,
            action="delete_project",
            target=str(proj_uuid),
            metadata={"project_id": str(proj_uuid), "project_name": getattr(project, "name", "")},
        )


@router.put("/{project_id}/flows/{flow_id}", response_model=FlowRead)
async def update_project_flow(
    project_id: str,
    flow_id: str,
    data: FlowUpdate,
    user: User = Depends(require_scope(SCOPE_FLOWS_WRITE)),
    db: AsyncSession = Depends(get_session),
):
    try:
        proj_uuid = uuid.UUID(project_id)
        fl_uuid = uuid.UUID(flow_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid UUID")

    await verify_project_role(db, proj_uuid, user, min_role="admin")
    flow_service = FlowService(db)
    flow = await flow_service.update_flow(fl_uuid, data)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


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


from fastapi import Query
from sqlalchemy import select
from app.modules.projects.models import Project
from app.modules.product_graph.service import ProductGraphService
from app.modules.product_graph.schemas import GraphDiff, DiscoveryResult


async def _get_project_with_auth(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> Project:
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this project")
    return project


@router.get("/{project_id}/product-graph")
async def get_product_graph(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Retrieve the full structured Product Graph for a project."""
    await _get_project_with_auth(db, project_id, user.id)
    service = ProductGraphService(db)
    return await service.export(project_id)


@router.put("/{project_id}/product-graph")
async def update_product_graph(
    project_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Apply manual edits or merge discoveries into the project's Product Graph."""
    await _get_project_with_auth(db, project_id, user.id)
    service = ProductGraphService(db)
    if "entity_type" in data and "entity_id" in data and "patch" in data:
        await service.merge_user_edit(
            project_id=project_id,
            entity_type=data["entity_type"],
            entity_id=uuid.UUID(str(data["entity_id"])),
            patch=data["patch"],
        )
        return await service.export(project_id)
    else:
        disc_result = DiscoveryResult.model_validate(data)
        return await service.upsert_from_discovery(project_id, disc_result)


@router.get("/{project_id}/product-graph/diff", response_model=GraphDiff)
async def get_product_graph_diff(
    project_id: uuid.UUID,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Compute structural differences between two versions of the Product Graph."""
    await _get_project_with_auth(db, project_id, user.id)
    service = ProductGraphService(db)
    return await service.diff(from_version, to_version, project_id)


from app.modules.flows.generator.schemas import GenerationRequest, GenerationResult
from app.modules.flows.service import FlowService


@router.post("/{project_id}/flows:generate", response_model=GenerationResult)
async def generate_flows_endpoint(
    project_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Generate executable test flows from the project's Product Graph."""
    await _get_project_with_auth(db, project_id, user.id)
    req_dict = dict(data)
    req_dict["project_id"] = project_id
    gen_request = GenerationRequest.model_validate(req_dict)
    service = FlowService(db)
    return await service.generate_flows(project_id, request=gen_request)


@router.post("/{project_id}/flows:evaluate-stale")
async def evaluate_stale_flows_endpoint(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Re-evaluate all stale flows in a project against the current Product Graph."""
    await _get_project_with_auth(db, project_id, user.id)
    service = FlowService(db)
    return await service.evaluate_stale_flows(project_id)


