"""Integrations API routes: GitHub & GitLab webhooks and repository connections."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.modules.integrations.github.webhook import verify_github_signature
from app.modules.integrations.gitlab.webhook import verify_gitlab_token
from app.modules.integrations.models import Integration
from app.modules.integrations.orchestrator import IntegrationOrchestrator
from app.modules.integrations.repository import IntegrationRepository
from app.modules.integrations.schemas import (
    IntegrationCreate,
    IntegrationEventRead,
    IntegrationRead,
)
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])
project_integrations_router = APIRouter(tags=["project-integrations"])


async def _run_orchestrator_task(event_id: uuid.UUID, pr_num: int | None, db_session_factory):
    """Background execution task for webhook event."""
    from app.infrastructure.database.session import async_session_factory

    async with async_session_factory() as session:
        repo = IntegrationRepository(session)
        event = await session.get(IntegrationEvent, event_id) if hasattr(session, "get") else None
        if not event:
            from sqlalchemy import select
            from app.modules.integrations.models import IntegrationEvent
            res = await session.execute(select(IntegrationEvent).where(IntegrationEvent.id == event_id))
            event = res.scalar_one_or_none()
        if event:
            orchestrator = IntegrationOrchestrator(session)
            try:
                await orchestrator.handle_event(event, pr_or_mr_id=pr_num)
            except Exception as e:
                logger.exception("Background orchestrator execution failed: %s", e)


# ---------------------------------------------------------------------------
# Webhook Endpoints
# ---------------------------------------------------------------------------

@router.post("/github/webhook")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
    db: AsyncSession = Depends(get_session),
):
    """Receive and verify GitHub webhooks for PR automated continuous validation."""
    body_bytes = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    repo_info = payload.get("repository", {})
    repo_full_name = repo_info.get("full_name") or repo_info.get("name")
    if not repo_full_name:
        raise HTTPException(status_code=400, detail="Missing repository in payload")

    repo = IntegrationRepository(db)
    integration = await repo.get_by_provider_and_repo("github", repo_full_name)
    if not integration:
        raise HTTPException(status_code=404, detail=f"No integration registered for repository '{repo_full_name}'")

    secret, _ = await repo.get_decrypted_secrets(integration)
    if not verify_github_signature(body_bytes, secret, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"Event '{x_github_event}' is not pull_request"}

    action = payload.get("action")
    if action not in ("opened", "reopened", "synchronize"):
        return {"status": "ignored", "reason": f"Pull request action '{action}' is not tracked"}

    delivery_id = x_github_delivery or str(uuid.uuid4())
    event = await repo.create_event(
        integration_id=integration.id,
        provider_event_id=delivery_id,
        event_type=f"pull_request.{action}",
        payload=payload,
    )

    pr_num = payload.get("pull_request", {}).get("number")

    async def _safe_run_github():
        try:
            orch = IntegrationOrchestrator(db)
            await orch.handle_event(event, pr_or_mr_id=pr_num)
        except Exception as e:
            logger.warning("Background GitHub orchestrator execution completed with: %s", e)

    background_tasks.add_task(_safe_run_github)

    return {"status": "accepted", "event_id": str(event.id), "delivery_id": delivery_id}


@router.post("/gitlab/webhook")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: str | None = Header(None, alias="X-Gitlab-Token"),
    x_gitlab_event: str | None = Header(None, alias="X-Gitlab-Event"),
    db: AsyncSession = Depends(get_session),
):
    """Receive and verify GitLab webhooks for MR automated continuous validation."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    project_info = payload.get("project", {})
    project_id = str(project_info.get("id") or project_info.get("path_with_namespace") or "")
    if not project_id:
        raise HTTPException(status_code=400, detail="Missing project information in payload")

    repo = IntegrationRepository(db)
    integration = await repo.get_by_provider_and_repo("gitlab", project_id)
    if not integration and project_info.get("path_with_namespace"):
        integration = await repo.get_by_provider_and_repo("gitlab", project_info["path_with_namespace"])

    if not integration:
        raise HTTPException(status_code=404, detail=f"No integration registered for project '{project_id}'")

    secret, _ = await repo.get_decrypted_secrets(integration)
    if not verify_gitlab_token(x_gitlab_token, secret):
        raise HTTPException(status_code=401, detail="Invalid GitLab webhook token")

    event_type = payload.get("event_type") or (x_gitlab_event or "").lower()
    if "merge_request" not in event_type and "merge request" not in event_type:
        return {"status": "ignored", "reason": "Event is not merge_request"}

    action = payload.get("object_attributes", {}).get("action")
    if action not in ("open", "reopen", "update"):
        return {"status": "ignored", "reason": f"Merge request action '{action}' is not tracked"}

    delivery_id = str(uuid.uuid4())
    event = await repo.create_event(
        integration_id=integration.id,
        provider_event_id=delivery_id,
        event_type=f"merge_request.{action}",
        payload=payload,
    )

    mr_iid = payload.get("object_attributes", {}).get("iid")

    async def _safe_run_gitlab():
        try:
            orch = IntegrationOrchestrator(db)
            await orch.handle_event(event, pr_or_mr_id=mr_iid)
        except Exception as e:
            logger.warning("Background GitLab orchestrator execution completed with: %s", e)

    background_tasks.add_task(_safe_run_gitlab)

    return {"status": "accepted", "event_id": str(event.id), "delivery_id": delivery_id}


# ---------------------------------------------------------------------------
# Project Integration Management
# ---------------------------------------------------------------------------

@project_integrations_router.post("/projects/{project_id}/integrations", status_code=status.HTTP_201_CREATED, response_model=IntegrationRead)
async def create_project_integration(
    project_id: str,
    data: IntegrationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Connect a GitHub repository or GitLab project to a Kova project."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    proj_repo = ProjectRepository(db)
    project = await proj_repo.get_by_id(p_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this project")

    repo = IntegrationRepository(db)
    integration = await repo.create(
        project_id=p_uuid,
        provider=data.provider,
        provider_repo_id=data.provider_repo_id,
        webhook_secret=data.webhook_secret,
        access_token=data.access_token,
        provider_installation_id=data.provider_installation_id,
        default_branch=data.default_branch,
        kova_config_path=data.kova_config_path,
    )
    return integration


@project_integrations_router.get("/projects/{project_id}/integrations", response_model=list[IntegrationRead])
async def list_project_integrations(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List all connected source control integrations for a project."""
    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid project ID")

    proj_repo = ProjectRepository(db)
    project = await proj_repo.get_by_id(p_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this project")

    repo = IntegrationRepository(db)
    return await repo.list_by_project(p_uuid)


@project_integrations_router.delete("/projects/{project_id}/integrations/{integration_id}")
async def deactivate_project_integration(
    project_id: str,
    integration_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Deactivate a source control integration without erasing historic events."""
    try:
        p_uuid = uuid.UUID(project_id)
        i_uuid = uuid.UUID(integration_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")

    proj_repo = ProjectRepository(db)
    project = await proj_repo.get_by_id(p_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    repo = IntegrationRepository(db)
    integration = await repo.get_by_id(i_uuid)
    if not integration or integration.project_id != p_uuid:
        raise HTTPException(status_code=404, detail="Integration not found")

    deactivated = await repo.deactivate(i_uuid)
    return {"status": "deactivated", "success": deactivated}
