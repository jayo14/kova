"""Exploration API endpoints.

Handles product exploration lifecycle: create session, check status,
submit credentials, answer role questions, cancel, and stream live SSE events.
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_current_user, get_session
from app.config.settings import settings
from app.modules.exploration.models import ExplorationStatus
from app.modules.exploration.repository import (
    ExplorationEventRepository,
    ExplorationRepository,
)
from app.modules.exploration.schemas import (
    ExplorationAnswerSubmit,
    ExplorationCancelResponse,
    ExplorationCreate,
    ExplorationCredentialSubmit,
    ExplorationCreateAccount,
    ExplorationEventRead,
    ExplorationRead,
    PromoteMissionRequest,
)
from app.modules.exploration.service import ExplorationService
from app.modules.auth.rbac import verify_project_role
from app.modules.flows.schemas import FlowRead
from app.modules.flows.service import FlowService
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exploration", tags=["exploration"])


async def _get_authorized_session(
    session_id: str,
    user_id: uuid.UUID,
    db: AsyncSession,
):
    try:
        parsed_id = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid exploration session ID",
        )

    repo = ExplorationRepository(db)
    session = await repo.get_by_id(parsed_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exploration session not found",
        )
    if session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: exploration session belongs to another user",
        )
    return session


@router.post("/", response_model=ExplorationRead, status_code=status.HTTP_201_CREATED)
async def create_exploration(
    data: ExplorationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Start an autonomous exploration session for a target URL."""
    service = ExplorationService(db)
    session = await service.create_and_start_exploration(data, user.id)
    return session


@router.get("/{session_id}", response_model=ExplorationRead)
async def get_exploration(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get the current state of an exploration session."""
    session = await _get_authorized_session(session_id, user.id, db)
    return session


from app.modules.credentials.schemas import CredentialRead
from app.modules.credentials.service import CredentialService
from app.modules.projects.repository import ProjectRepository


@router.get("/{session_id}/credentials", response_model=list[CredentialRead])
async def list_exploration_credentials(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List available credentials stored for the project associated with this exploration session."""
    session = await _get_authorized_session(session_id, user.id, db)
    service = CredentialService(db)
    if session.project_id:
        creds = await service.list_credentials(session.project_id)
        if creds:
            return creds

    # Fallback: check if other projects by the user for the same host have credentials
    if session.url:
        import re
        from urllib.parse import urlparse
        parsed = urlparse(session.url)
        clean_host = re.sub(r"^www\d*\.", "", (parsed.hostname or "").lower())
        proj_repo = ProjectRepository(db)
        user_projects = await proj_repo.list_by_user(user.id, limit=50)
        for p in user_projects:
            p_host = re.sub(r"^www\d*\.", "", (urlparse(p.base_url).hostname or "").lower())
            if p_host == clean_host:
                creds = await service.list_credentials(p.id)
                if creds:
                    return creds

    return []


@router.post("/{session_id}/credentials", response_model=ExplorationRead)
async def submit_exploration_credentials(
    session_id: str,
    data: ExplorationCredentialSubmit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Submit credentials for an exploration session blocked by authentication."""
    await _get_authorized_session(session_id, user.id, db)
    service = ExplorationService(db)
    try:
        updated = await service.submit_credentials(uuid.UUID(session_id), user.id, data)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/create-account", response_model=ExplorationRead)
async def create_exploration_account(
    session_id: str,
    data: ExplorationCreateAccount,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Attempt to create an account on the target site automatically."""
    await _get_authorized_session(session_id, user.id, db)
    service = ExplorationService(db)
    updated = await service.create_account(uuid.UUID(session_id), user.id, data)
    return updated


@router.post("/{session_id}/answer", response_model=ExplorationRead)
async def submit_exploration_answer(
    session_id: str,
    data: ExplorationAnswerSubmit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Submit answer to role selection or clarification question."""
    await _get_authorized_session(session_id, user.id, db)
    service = ExplorationService(db)
    updated = await service.submit_answer(uuid.UUID(session_id), user.id, data)
    return updated


@router.post("/{session_id}/cancel", response_model=ExplorationCancelResponse)
async def cancel_exploration(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Cancel an active exploration session."""
    await _get_authorized_session(session_id, user.id, db)
    service = ExplorationService(db)
    cancelled = await service.cancel_session(uuid.UUID(session_id), user.id)
    return ExplorationCancelResponse(
        id=uuid.UUID(session_id),
        status=cancelled.status if cancelled else ExplorationStatus.CANCELLED.value,
        message="Exploration stopped",
    )


@router.post("/{session_id}/navigate/{action}")
async def navigate_exploration(
    session_id: str,
    action: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Navigate the browser for an active exploration (back, forward, reload)."""
    if action not in ("back", "forward", "reload"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be one of: back, forward, reload",
        )

    await _get_authorized_session(session_id, user.id, db)
    service = ExplorationService(db)
    result = await service.navigate_browser(uuid.UUID(session_id), user.id, action)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result


@router.post("/{session_id}/missions/{mission_id}/promote", response_model=FlowRead, status_code=status.HTTP_201_CREATED)
@router.post("/{session_id}/missions/{mission_id}:promote", response_model=FlowRead, status_code=status.HTTP_201_CREATED)
async def promote_mission(
    session_id: str,
    mission_id: str,
    data: PromoteMissionRequest = PromoteMissionRequest(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Promote an exploration candidate mission into a project Flow."""
    session = await _get_authorized_session(session_id, user.id, db)

    target_mission = None
    target_idx = -1
    for idx, m in enumerate(session.candidate_missions or []):
        if str(m.get("id")) == mission_id or str(m.get("flow_id")) == mission_id:
            target_mission = m
            target_idx = idx
            break

    if target_mission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate mission '{mission_id}' not found in exploration session",
        )

    resolved_project_id = data.project_id or session.project_id
    if not resolved_project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot promote mission without an associated project",
        )

    await verify_project_role(db, resolved_project_id, user, min_role="tester")

    flow_service = FlowService(db)
    flow = await flow_service.create_from_mission(
        project_id=resolved_project_id,
        mission=target_mission,
        user_id=user.id,
        activate_immediately=data.activate_immediately,
        name=data.name,
    )

    updated_missions = list(session.candidate_missions or [])
    if 0 <= target_idx < len(updated_missions):
        updated_entry = dict(updated_missions[target_idx])
        updated_entry["promoted"] = True
        updated_entry["flow_id"] = str(flow.id)
        updated_missions[target_idx] = updated_entry
        session_repo = ExplorationRepository(db)
        await session_repo.update_status(session.id, candidate_missions=updated_missions)

    return flow


@router.get("/{session_id}/events", response_model=list[ExplorationEventRead])
async def get_exploration_events(
    session_id: str,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get persisted events for an exploration session."""
    session = await _get_authorized_session(session_id, user.id, db)
    event_repo = ExplorationEventRepository(db)
    events = await event_repo.list_by_session(session.id, skip=skip, limit=limit)
    return events


@router.get("/screenshots/{key}")
async def get_screenshot(
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Redirect to Supabase public URL for a screenshot.

    Ownership-checked: the exploration_id embedded in the key must belong to
    the requesting user. Unauthenticated access is refused — screenshots show
    application state (possibly authenticated) and are sensitive.
    """
    from app.engine.browser.screenshot_storage import screenshot_storage

    # Extract exploration_id from key (format: {exploration_id}_{uuid}.png)
    parts = key.split("_", 1)
    if len(parts) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Screenshot not found",
        )
    exploration_id = parts[0]
    try:
        session_uuid = uuid.UUID(exploration_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")

    # Ownership check via the exploration session
    repo = ExplorationRepository(db)
    session = await repo.get_by_id_and_user(session_uuid, user.id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found")

    public_url = screenshot_storage.get_public_url(key, exploration_id)
    if not public_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Screenshot storage not configured",
        )
    return RedirectResponse(url=public_url, status_code=status.HTTP_302_FOUND)


@router.get("/{session_id}/events/stream")
async def stream_exploration_events(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """Server-Sent Events (SSE) live event stream for exploration progress."""
    from app.infrastructure.database.session import async_session_factory

    async with async_session_factory() as auth_db:
        session = await _get_authorized_session(session_id, user.id, auth_db)
        parsed_id = session.id

    async def event_generator() -> AsyncGenerator[str, None]:
        seen_event_ids: set[uuid.UUID] = set()
        seen_statuses: set[str] = set()
        has_missions_event = False
        ready_wait_cycles = 0
        ping_counter = 0

        try:
            # Send initial connected heartbeat to immediately flush response headers past buffering proxies
            yield ": connected\n\n"

            while True:
                if await request.is_disconnected():
                    break

                chunks_to_send: list[str] = []
                should_terminate = False

                async with async_session_factory() as poll_db:
                    event_repo = ExplorationEventRepository(poll_db)
                    session_repo = ExplorationRepository(poll_db)

                    # Fetch any new events
                    events = await event_repo.list_by_session(parsed_id, limit=500)
                    for ev in events:
                        if ev.id not in seen_event_ids:
                            seen_event_ids.add(ev.id)
                            if ev.event_type == "missions":
                                has_missions_event = True
                            data_payload = {
                                "id": str(ev.id),
                                "exploration_id": str(ev.exploration_id),
                                "event_type": ev.event_type,
                                "payload": ev.payload,
                                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                            }
                            chunks_to_send.append(
                                f"id: {ev.id}\nevent: {ev.event_type}\ndata: {json.dumps(data_payload)}\n\n"
                            )

                    # Check if session is terminal
                    current_session = await session_repo.get_by_id(parsed_id)
                    if current_session:
                        terminal_statuses = {
                            ExplorationStatus.READY.value,
                            ExplorationStatus.COMPLETED.value,
                            ExplorationStatus.FAILED.value,
                            ExplorationStatus.CANCELLED.value,
                        }
                        # If READY, wait for candidate missions event up to a few cycles (~3s) so frontend receives them before done
                        if (
                            current_session.status == ExplorationStatus.READY.value
                            and not has_missions_event
                            and ready_wait_cycles < 6
                        ):
                            ready_wait_cycles += 1
                        elif current_session.status in terminal_statuses:
                            if current_session.status not in seen_statuses:
                                seen_statuses.add(current_session.status)
                                chunks_to_send.append(
                                    f"event: state_change\ndata: {json.dumps({'status': current_session.status})}\n\n"
                                )
                            chunks_to_send.append("event: done\ndata: {}\n\n")
                            should_terminate = True
                        else:
                            # Emit non-terminal state_change for new statuses
                            if current_session.status not in seen_statuses:
                                seen_statuses.add(current_session.status)
                                chunks_to_send.append(
                                    f"event: state_change\ndata: {json.dumps({'status': current_session.status})}\n\n"
                                )

                # Yield outside of the database session context
                for chunk in chunks_to_send:
                    yield chunk

                if should_terminate:
                    break

                # Heartbeat every ~15 seconds (60 * 0.25s)
                ping_counter += 1
                if ping_counter >= 60:
                    ping_counter = 0
                    yield ": ping\n\n"

                await asyncio.sleep(0.25)

        except Exception as e:
            logger.error("SSE generator error for session %s: %s", session_id, e)
            error_payload = {
                "exploration_id": session_id,
                "event_type": "error",
                "payload": {"message": "Stream interrupted due to internal error"},
                "created_at": None,
            }
            yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
