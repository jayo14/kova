"""WebSocket endpoint for live viewport streaming.

Streams Playwright browser screenshots to frontend via WebSocket.
Supports user takeover, pause/resume, and browser input.

Architecture:
- Binary frames: raw JPEG bytes (live viewport) — sourced from Redis pub/sub
  published by the worker/runner (never a Playwright object across processes)
- JSON control messages: state updates, browser metadata
- Auth: verifies user owns the execution before allowing connection
- Control: Redis pub/sub for cross-process agent↔human coordination
"""

import asyncio
import json
import logging
import secrets
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.api import get_current_user
from app.modules.users.models import User
from app.engine.execution.control import (
    ControlState,
    acquire_human_takeover,
    get_control_record,
    get_control_state,
    publish_command,
    queue_user_input,
    release_human_control,
    request_pause,
    request_resume,
    set_control_state,
    validate_human_interaction,
)

from app.engine.execution.stream import publish_state, subscribe_frames, subscribe_states

logger = logging.getLogger(__name__)
router = APIRouter()

# Active viewport connections: execution_id → WebSocket
_viewport_connections: dict[str, WebSocket] = {}

# Short-lived, single-use ticket store for WebSocket authentication
_ws_tickets: dict[str, dict[str, Any]] = {}


def create_ws_ticket(user_id: str, ttl_seconds: int = 30) -> str:
    """Issue a short-lived, single-use ticket for WebSocket authentication."""
    _clean_expired_tickets()
    ticket = secrets.token_urlsafe(32)
    _ws_tickets[ticket] = {
        "user_id": user_id,
        "expires_at": time.time() + ttl_seconds,
    }
    return ticket


def consume_ws_ticket(ticket: str) -> str | None:
    """Consume a single-use ticket. Returns user_id if valid, else None."""
    _clean_expired_tickets()
    if not ticket or ticket not in _ws_tickets:
        return None
    ticket_data = _ws_tickets.pop(ticket)
    if time.time() > ticket_data.get("expires_at", 0):
        return None
    return ticket_data.get("user_id")


def _clean_expired_tickets() -> None:
    now = time.time()
    expired = [t for t, data in _ws_tickets.items() if data.get("expires_at", 0) < now]
    for t in expired:
        _ws_tickets.pop(t, None)


@router.post("/viewport/ticket")
@router.post("/ws/ticket")
async def issue_viewport_ticket(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Issue a short-lived (~30s), single-use ticket for WebSocket authentication."""
    ticket = create_ws_ticket(str(user.id), ttl_seconds=30)
    return {"ticket": ticket, "expires_in": 30}


async def broadcast_frame(execution_id: str, frame_bytes: bytes, state: str = "observing"):
    """Send a frame to a directly-connected client (same-process only).

    Cross-process frames arrive via subscribe_frames() pumps below.
    """
    ws = _viewport_connections.get(execution_id)
    if ws and ws.client_state == WebSocketState.CONNECTED:
        try:
            header = json.dumps({"type": "frame", "state": state})
            await ws.send_text(header)
            await ws.send_bytes(frame_bytes)
        except Exception as e:
            logger.warning("Failed to broadcast frame: %s", e)


async def broadcast_state(execution_id: str, state: str, url: str = "", title: str = ""):
    """Broadcast state update to connected clients (and Redis for other processes)."""
    try:
        await publish_state(execution_id, state, url, title)
    except Exception:
        pass
    ws = _viewport_connections.get(execution_id)
    if ws and ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.send_json({
                "type": "state",
                "state": state,
                "url": url,
                "title": title,
            })
        except Exception:
            pass


async def broadcast_control_changed(execution_id: str, control: str):
    """Broadcast control state change to connected clients."""
    ws = _viewport_connections.get(execution_id)
    if ws and ws.client_state == WebSocketState.CONNECTED:
        try:
            await ws.send_json({
                "type": "control_changed",
                "control": control,
            })
        except Exception:
            pass


async def _verify_execution_access(execution_id: str, user_id: str, db: AsyncSession | None = None) -> bool:
    """Verify that the user owns the execution's project."""
    try:
        from app.infrastructure.database.session import async_session_factory
        from app.modules.executions.repository import ExecutionRepository
        from app.modules.flows.repository import FlowRepository
        from app.modules.projects.repository import ProjectRepository

        exec_uuid = uuid.UUID(execution_id)

        async def _check(session: AsyncSession) -> bool:
            exec_repo = ExecutionRepository(session)
            execution = await exec_repo.get_by_id(exec_uuid)
            if not execution:
                return False

            flow_repo = FlowRepository(session)
            flow = await flow_repo.get_by_id(execution.flow_id)
            if not flow:
                return False

            project_repo = ProjectRepository(session)
            project = await project_repo.get_by_id(flow.project_id)
            if not project:
                return False

            return str(project.user_id) == str(user_id)

        if db is not None:
            return await _check(db)
        else:
            async with async_session_factory() as session:
                return await _check(session)
    except Exception as e:
        logger.warning("Access verification failed: %s", e)
        return False


async def _authenticate_ws_token(token: str, db: AsyncSession | None = None) -> str | None:
    """Verify JWT or kova_ API token and return user_id. Returns None if invalid."""
    import jwt
    from app.config.settings import settings
    from app.modules.auth.dependencies import _get_jwt_secret

    if not token:
        return None

    if token.startswith("kova_"):
        from app.infrastructure.database.session import async_session_factory
        from app.modules.auth.token_service import verify_api_token
        try:
            if db is not None:
                api_tok = await verify_api_token(db, token)
                if api_tok:
                    return str(api_tok.user_id)
            else:
                async with async_session_factory() as session:
                    api_tok = await verify_api_token(session, token)
                    if api_tok:
                        return str(api_tok.user_id)
        except Exception as e:
            logger.warning("WebSocket API token verification failed: %s", e)
        return None

    secret = _get_jwt_secret()
    try:
        decode_options: dict = {"require": ["exp"]}
        audience = settings.OIDC_AUDIENCE
        issuer = settings.effective_jwt_issuer
        if not audience:
            decode_options["verify_aud"] = False
        if not issuer:
            decode_options["verify_iss"] = False

        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience or None,
            issuer=issuer,
            options=decode_options,
        )
        sub = payload.get("sub")
        if sub:
            uuid.UUID(str(sub))
            return str(sub)
    except Exception as e:
        logger.warning("WebSocket JWT auth failed: %s", e)

    return None


async def _pump_frames(execution_id: str, websocket: WebSocket) -> None:
    """Relay Redis frames to the WebSocket. Latest-wins via drop-stale queue."""
    while True:
        if websocket.client_state != WebSocketState.CONNECTED:
            return
        # subscribe_frames is an async generator; pull next frame
        agen = subscribe_frames(execution_id)
        try:
            async for jpeg, state in agen:
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                try:
                    header = json.dumps({"type": "frame", "state": state})
                    await websocket.send_text(header)
                    await websocket.send_bytes(jpeg)
                except WebSocketDisconnect:
                    return
                except Exception as e:
                    logger.debug("Frame send failed: %s", e)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Frame subscribe error: %s", e)
            await asyncio.sleep(0.5)


async def _pump_states(execution_id: str, websocket: WebSocket) -> None:
    """Relay Redis state messages to the WebSocket."""
    while True:
        if websocket.client_state != WebSocketState.CONNECTED:
            return
        agen = subscribe_states(execution_id)
        try:
            async for payload in agen:
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                try:
                    await websocket.send_json(payload)
                except WebSocketDisconnect:
                    return
                except Exception:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("State subscribe error: %s", e)
            await asyncio.sleep(0.5)


async def _pump_loop(execution_id: str, websocket: WebSocket) -> None:
    """Run frame + state pumps until disconnect."""
    frame_task = asyncio.create_task(_pump_frames(execution_id, websocket))
    state_task = asyncio.create_task(_pump_states(execution_id, websocket))
    done, pending = await asyncio.wait(
        {frame_task, state_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    for t in done:
        try:
            t.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Pump task ended: %s", e)


async def get_optional_session() -> AsyncSession | None:
    """Dependency placeholder that returns None so WebSockets do not hold open persistent DB sessions."""
    return None


@router.websocket("/ws/viewport/{execution_id}")
async def viewport_stream(
    websocket: WebSocket,
    execution_id: str,
    ticket: str = Query(default=""),
    token: str = Query(default=""),
    db: AsyncSession | None = Depends(get_optional_session),
):
    """WebSocket endpoint for live viewport streaming.

    Auth: Requires short-lived single-use ticket or valid session token.
    Ownership: Verifies user owns the execution's project.

    Protocol:
    - Server → Client: {"type": "frame", "state": "..."} + binary frame
    - Server → Client: {"type": "state", "state": "...", "url": "...", "title": "..."}
    - Server → Client: {"type": "control_changed", "control": "agent"|"human"}
    - Client → Server: {"type": "takeover_accept"}
    - Client → Server: {"type": "takeover_reject"}
    - Client → Server: {"type": "return_control"}
    - Client → Server: {"type": "input", "kind": "click", "x": 100, "y": 200}
    - Client → Server: {"type": "input", "kind": "type", "text": "hello"}
    - Client → Server: {"type": "nav", "kind": "back"|"forward"|"reload"}
    """
    raw_ticket = ticket if isinstance(ticket, str) else ""
    raw_token = token if isinstance(token, str) else ""

    user_id = None
    if raw_ticket:
        user_id = consume_ws_ticket(raw_ticket)
    elif raw_token:
        user_id = await _authenticate_ws_token(raw_token, db=db)

    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if not await _verify_execution_access(execution_id, user_id, db=db):
        await websocket.close(code=4003, reason="Forbidden")
        return

    await websocket.accept()
    _viewport_connections[execution_id] = websocket
    logger.info("Viewport connected for execution %s (user %s)", execution_id, user_id)

    pump_task = asyncio.create_task(_pump_loop(execution_id, websocket))

    # Send current authoritative control state immediately
    active_lease_id: str | None = None
    try:
        rec = await get_control_record(execution_id)
        control_str = "human" if rec.state == ControlState.HUMAN_CONTROL else ("paused" if rec.state == ControlState.PAUSED else "agent")
        await websocket.send_json({
            "type": "control_changed",
            "control": control_str,
            "state": rec.state.value if hasattr(rec.state, "value") else str(rec.state),
            "generation": rec.generation,
            "checkpoint": rec.checkpoint,
        })
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type in ("takeover_accept", "takeover", "acquire_control"):
                ok, lease_or_err, rec = await acquire_human_takeover(execution_id, client_id=str(user_id))
                if ok:
                    active_lease_id = lease_or_err
                    await websocket.send_json({
                        "type": "takeover_granted",
                        "lease_id": active_lease_id,
                        "generation": rec.generation,
                        "control": "human",
                        "state": "user_control",
                    })
                    await websocket.send_json({
                        "type": "control_changed",
                        "control": "human",
                        "lease_id": active_lease_id,
                        "generation": rec.generation,
                    })
                    logger.info("User takeover accepted for %s (lease: %s)", execution_id, active_lease_id)
                else:
                    await websocket.send_json({
                        "type": "takeover_rejected",
                        "reason": lease_or_err,
                    })
                    logger.warning("User takeover rejected for %s: %s", execution_id, lease_or_err)

            elif msg_type == "takeover_reject":
                await websocket.send_json({"type": "control_changed", "control": "agent"})
                logger.info("User takeover rejected by client for %s", execution_id)

            elif msg_type in ("return_control", "release_control"):
                lease = msg.get("lease_id") or active_lease_id
                ok, err, rec = await release_human_control(execution_id, client_id=str(user_id), lease_id=lease)
                active_lease_id = None
                await websocket.send_json({
                    "type": "control_changed",
                    "control": "agent",
                    "state": "resuming",
                    "generation": rec.generation,
                })
                logger.info("User returned control for %s", execution_id)

            elif msg_type == "pause":
                rec = await request_pause(execution_id, reason="User requested pause via live view")
                await websocket.send_json({
                    "type": "control_changed",
                    "control": "paused",
                    "state": "paused",
                    "generation": rec.generation,
                })

            elif msg_type == "resume":
                rec = await request_resume(execution_id)
                await websocket.send_json({
                    "type": "control_changed",
                    "control": "agent",
                    "state": "resuming",
                    "generation": rec.generation,
                })

            elif msg_type in ("nav", "input"):
                lease = msg.get("lease_id") or active_lease_id
                gen = msg.get("generation")
                valid, err = await validate_human_interaction(
                    execution_id,
                    lease_id=lease,
                    client_id=str(user_id),
                    generation=gen,
                )
                if not valid:
                    logger.debug("Rejected interaction on %s: %s", execution_id, err)
                    await websocket.send_json({"type": "interaction_rejected", "reason": err})
                else:
                    if msg_type == "nav":
                        kind = msg.get("kind", "")
                        if kind in ("back", "forward", "reload"):
                            await queue_user_input(execution_id, {"kind": f"nav_{kind}", "lease_id": lease})
                    else:
                        await queue_user_input(execution_id, msg)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})


    except WebSocketDisconnect:
        logger.info("Viewport disconnected for execution %s", execution_id)
    except Exception as e:
        logger.warning("Viewport error for %s: %s", execution_id, e)
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        _viewport_connections.pop(execution_id, None)
