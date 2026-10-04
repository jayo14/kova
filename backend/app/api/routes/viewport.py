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
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.infrastructure.database.session import get_session

from app.engine.execution.control import (
    set_control_state,
    get_control_state,
    publish_command,
    queue_user_input,
)
from app.engine.execution.stream import publish_state, subscribe_frames, subscribe_states

logger = logging.getLogger(__name__)
router = APIRouter()

# Active viewport connections: execution_id → WebSocket
_viewport_connections: dict[str, WebSocket] = {}


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
        if settings.is_production or settings.OIDC_ISSUER_URL:
            return None
        return str(uuid.UUID("00000000-0000-0000-0000-000000000001"))

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


@router.websocket("/ws/viewport/{execution_id}")
async def viewport_stream(
    websocket: WebSocket,
    execution_id: str,
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_session),
):
    """WebSocket endpoint for live viewport streaming.

    Auth: Requires valid session token via query parameter.
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
    user_id = await _authenticate_ws_token(token, db=db)
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

    # Send current control state immediately
    try:
        current_control = await get_control_state(execution_id)
        await websocket.send_json({"type": "control_changed", "control": current_control})
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
            current_state = await get_control_state(execution_id)

            if msg_type == "takeover_accept" or msg_type == "takeover":
                await set_control_state(execution_id, "human")
                await publish_command(execution_id, "pause")
                await websocket.send_json({"type": "state", "state": "user_control"})
                await websocket.send_json({"type": "control_changed", "control": "human"})
                logger.info("User takeover accepted for %s", execution_id)

            elif msg_type == "takeover_reject":
                await set_control_state(execution_id, "agent")
                await websocket.send_json({"type": "state", "state": "observing"})
                await websocket.send_json({"type": "control_changed", "control": "agent"})
                logger.info("User takeover rejected for %s", execution_id)

            elif msg_type == "return_control":
                await set_control_state(execution_id, "agent")
                await publish_command(execution_id, "resume")
                await websocket.send_json({"type": "state", "state": "resuming"})
                await websocket.send_json({"type": "control_changed", "control": "agent"})
                logger.info("User returned control for %s", execution_id)

            elif msg_type == "nav" and current_state in ("human", "paused"):
                kind = msg.get("kind", "")
                if kind == "back":
                    await queue_user_input(execution_id, {"kind": "nav_back"})
                elif kind == "forward":
                    await queue_user_input(execution_id, {"kind": "nav_forward"})
                elif kind == "reload":
                    await queue_user_input(execution_id, {"kind": "nav_reload"})

            elif msg_type == "input" and current_state in ("human", "paused"):
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
