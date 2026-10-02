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
)
from app.modules.exploration.service import ExplorationService
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
    session = await repo.get_by_id_and_user(parsed_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exploration session not found",
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
    updated = await service.submit_credentials(uuid.UUID(session_id), user.id, data)
    return updated


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
    db: AsyncSession = Depends(get_session),
):
    """Server-Sent Events (SSE) live event stream for exploration progress."""
    session = await _get_authorized_session(session_id, user.id, db)
    parsed_id = session.id

    async def event_generator() -> AsyncGenerator[str, None]:
        from app.infrastructure.database.session import async_session_factory
        seen_event_ids: set[uuid.UUID] = set()
        seen_statuses: set[str] = set()
        ping_counter = 0

        try:
            while True:
                if await request.is_disconnected():
                    break

                async with async_session_factory() as poll_db:
                    event_repo = ExplorationEventRepository(poll_db)
                    session_repo = ExplorationRepository(poll_db)

                    # Fetch any new events
                    events = await event_repo.list_by_session(parsed_id, limit=200)
                    for ev in events:
                        if ev.id not in seen_event_ids:
                            seen_event_ids.add(ev.id)
                            data_payload = {
                                "id": str(ev.id),
                                "exploration_id": str(ev.exploration_id),
                                "event_type": ev.event_type,
                                "payload": ev.payload,
                                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                            }
                            yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {json.dumps(data_payload)}\n\n"

                    # Check if session is terminal
                    current_session = await session_repo.get_by_id(parsed_id)
                    if current_session:
                        terminal_statuses = {
                            ExplorationStatus.READY.value,
                            ExplorationStatus.COMPLETED.value,
                            ExplorationStatus.FAILED.value,
                            ExplorationStatus.CANCELLED.value,
                            ExplorationStatus.AUTH_REQUIRED.value,
                            ExplorationStatus.ASKING.value,
                        }
                        if current_session.status in terminal_statuses:
                            # Ensure any remaining events are completely flushed
                            final_events = await event_repo.list_by_session(parsed_id, limit=500)
                            for ev in final_events:
                                if ev.id not in seen_event_ids:
                                    seen_event_ids.add(ev.id)
                                    data_payload = {
                                        "id": str(ev.id),
                                        "exploration_id": str(ev.exploration_id),
                                        "event_type": ev.event_type,
                                        "payload": ev.payload,
                                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                                    }
                                    yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {json.dumps(data_payload)}\n\n"

                        # If status is READY, ensure candidate_missions have been delivered
                        has_missions_event = any(ev.event_type == "missions" for ev in final_events)
                        if current_session.status == ExplorationStatus.READY.value and not has_missions_event:
                            await asyncio.sleep(0.5)
                            retry_events = await event_repo.list_by_session(parsed_id, limit=500)
                            for ev in retry_events:
                                if ev.id not in seen_event_ids:
                                    seen_event_ids.add(ev.id)
                                    data_payload = {
                                        "id": str(ev.id),
                                        "exploration_id": str(ev.exploration_id),
                                        "event_type": ev.event_type,
                                        "payload": ev.payload,
                                        "created_at": ev.created_at.isoformat() if ev.created_at else None,
                                    }
                                    yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {json.dumps(data_payload)}\n\n"

                        # Emit terminal state_change if not already emitted
                        if current_session.status not in seen_statuses:
                            seen_statuses.add(current_session.status)
                            yield f"event: state_change\ndata: {json.dumps({'status': current_session.status})}\n\n"
                        yield "event: done\ndata: {}\n\n"
                        break
                    else:
                        # Emit non-terminal state_change for new statuses
                        if current_session.status not in seen_statuses:
                            seen_statuses.add(current_session.status)
                            yield f"event: state_change\ndata: {json.dumps({'status': current_session.status})}\n\n"

                    # Heartbeat every ~15 seconds — must stay inside the loop
                    ping_counter += 1
                    if ping_counter >= 30:
                        ping_counter = 0
                        yield ": ping\n\n"

                await asyncio.sleep(0.5)

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
