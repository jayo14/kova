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

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api import get_current_user, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.api import get_current_user
from app.modules.users.models import User
from app.engine.execution.control import (
    ControlState,
    TERMINAL_CONTROL_STATES,
    acquire_human_takeover,
    get_control_record,
    get_control_state,
    publish_command,
    queue_user_input,
    release_human_control,
    renew_human_control_lease,
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


def derive_control_value(state: ControlState) -> str:
    """Map ControlState to the client-facing control value.

    These are server-derived truths. Pending states are explicit — the client
    must never show "You have control" or "Agent running" based on them.
    """
    if state in TERMINAL_CONTROL_STATES:
        return "stopped"
    return {
        ControlState.RUNNING: "agent",
        ControlState.PAUSE_REQUESTED: "agent_pausing",
        ControlState.PAUSED: "paused",
        ControlState.QUIESCING: "human_pending",
        ControlState.HUMAN_CONTROL: "human",
        ControlState.RECONCILING: "reconciling",
        ControlState.WAITING_FOR_USER: "waiting_user",
        ControlState.RESUME_REQUESTED: "resume_pending",
    }.get(state, "agent")


class FrameRelay:
    """Per-viewer frame relay stats: seq, prompt acks, drop-stale, quality."""

    MAX_UNACKED = 3           # hold newest frames until acks catch up
    ACK_WAIT_SECONDS = 1.0    # max hold while a slow client catches up

    def __init__(self) -> None:
        self.quality_last_forwarded = 0
        self.sent_ts: dict[int, float] = {}
        self.high_water = 0          # highest seq sent
        self.acked_seq = 0           # highest seq acked (or dropped) by client
        self.forwarded = 0
        self.dropped_queue = 0       # producer-side latest-wins drops
        self.dropped_newest = 0      # replaced by a newer frame during hold
        self.last_rtt_ms: float | None = None
        self.fps = 0.0

    def begin_send(self) -> int:
        seq = self.high_water + 1
        self.high_water = seq
        self.forwarded += 1
        self.sent_ts[seq] = time.time()
        return seq

    def settle_up_to(self, seq: int) -> None:
        if seq <= self.acked_seq:
            return
        self.acked_seq = seq
        t_send = self.sent_ts.pop(seq, None)
        if t_send is not None:
            self.last_rtt_ms = round((time.time() - t_send) * 1000, 1)
        for done in [s for s in list(self.sent_ts) if s <= seq]:
            self.sent_ts.pop(done, None)

    @property
    def unacked(self) -> int:
        return max(0, self.high_water - self.acked_seq)

    def quality(self) -> dict[str, Any]:
        return {
            "type": "connection_quality",
            "fps": round(self.fps, 1),
            "unacked": self.unacked,
            "dropped": self.dropped_queue + self.dropped_newest,
            "rtt_ms": self.last_rtt_ms,
        }


async def _pump_frames(execution_id: str, websocket: WebSocket, relay: FrameRelay) -> None:
    """Relay Redis frames to the WebSocket with newest-wins delivery.

    A single-slot handoff queue keeps only the freshest frame when the producer
    outpaces a viewer. Sends are ack-aware: while too many frames are unacked
    we hold (not buffer) the newest frame until the client catches up or the
    hold expires — stale frames are dropped, never queued up.
    """
    incoming: asyncio.Queue[tuple[bytes, str, str]] = asyncio.Queue(maxsize=1)

    async def producer() -> None:
        agen = subscribe_frames(execution_id)
        try:
            async for jpeg, state, masking in agen:
                frame = (jpeg, state, masking)
                if incoming.full():
                    try:
                        incoming.get_nowait()
                        relay.dropped_queue += 1
                    except asyncio.QueueEmpty:
                        pass
                try:
                    incoming.put_nowait(frame)
                except asyncio.QueueFull:
                    relay.dropped_queue += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("Frame producer error: %s", e)

    producer_task = asyncio.create_task(producer())
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                jpeg, state, masking = await asyncio.wait_for(incoming.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            # Slow client: hold the newest frame until acks catch up.
            if relay.unacked >= relay.MAX_UNACKED:
                deadline = time.time() + relay.ACK_WAIT_SECONDS
                while time.time() < deadline and relay.unacked >= relay.MAX_UNACKED:
                    if not incoming.empty():
                        incoming.get_nowait()
                        relay.dropped_newest += 1
                    await asyncio.sleep(0.02)
            seq = relay.begin_send()
            try:
                header = json.dumps({
                    "type": "frame",
                    "state": state,
                    "seq": seq,
                    "masking": masking,
                    "ts": time.time(),
                })
                await websocket.send_text(header)
                await websocket.send_bytes(jpeg)
            except WebSocketDisconnect:
                return
            except Exception as e:
                logger.debug("Frame send failed: %s", e)
                return
    except asyncio.CancelledError:
        raise
    finally:
        producer_task.cancel()


async def _pump_control(execution_id: str, websocket: WebSocket, last_sent: dict[str, Any]) -> None:
    """Poll the authoritative control record and push real changes.

    This is the server-confirmed control truth the client displays. Request
    handlers only send *pending* acknowledgements; confirmed control changes
    arrive here when the control record actually moves.
    """
    while websocket.client_state == WebSocketState.CONNECTED:
        try:
            rec = await get_control_record(execution_id)
            control = derive_control_value(rec.state)
            token = f"{control}:{rec.generation}"
            if token != last_sent.get("token"):
                last_sent["token"] = token
                lease_expires = rec.lease_expires_at
                if lease_expires is not None and hasattr(lease_expires, "isoformat"):
                    lease_expires = lease_expires.isoformat()
                await websocket.send_json({
                    "type": "control_changed",
                    "control": control,
                    "state": rec.state.value,
                    "generation": rec.generation,
                    "lease_id": rec.lease_id,
                    "lease_expires_at": lease_expires,
                    "owner": rec.owner,
                    "checkpoint": rec.checkpoint,
                })
        except Exception as e:
            logger.debug("Control poll failed: %s", e)
        await asyncio.sleep(1.0)


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


async def _pump_loop(execution_id: str, websocket: WebSocket, relay: FrameRelay) -> None:
    """Run frame + state + control pumps until disconnect."""
    frame_task = asyncio.create_task(_pump_frames(execution_id, websocket, relay))
    state_task = asyncio.create_task(_pump_states(execution_id, websocket))
    control_last: dict[str, Any] = {"token": None}
    control_task = asyncio.create_task(_pump_control(execution_id, websocket, control_last))
    # Periodic connection-quality push (computed from relay stats).
    async def _quality_pump() -> None:
        while websocket.client_state == WebSocketState.CONNECTED:
            await asyncio.sleep(3.0)
            if relay.high_water == 0:
                continue
            # fps measured over the last window: reset counter each period
            window = relay.forwarded - relay.quality_last_forwarded
            relay.fps = window / 3.0
            relay.quality_last_forwarded = relay.forwarded
            try:
                await websocket.send_json(relay.quality())
            except Exception:
                return
    quality_task = asyncio.create_task(_quality_pump())
    done, pending = await asyncio.wait(
        {frame_task, state_task, control_task, quality_task},
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
    db: AsyncSession = Depends(get_session),
):
    """WebSocket endpoint for live viewport streaming.

    Auth: The first client message must contain a short-lived, single-use ticket
    issued by POST /viewport/ticket. Secrets are never accepted in WebSocket URLs.
    Ownership: Verifies user owns the execution's project.

    Protocol:
    - Server → Client: {"type": "frame", "state": "...", "seq": N,
      "masking": "masked"|"off"|"unknown", "ts": unix} + binary frame
    - Server → Client: {"type": "state", "state": "...", "url": "...", "title": "..."}
    - Server → Client: {"type": "control_changed", "control": "agent"|"human" |
      "paused"|"human_pending"|"agent_pausing"|"reconciling"|"stopped",
      "lease_id", "lease_expires_at"} — emitted by the authoritative control
      poll whenever the control record actually changes
    - Server → Client: {"type": "masking_status", "masking": "..."}
    - Server → Client: {"type": "connection_quality", "fps", "unacked",
      "dropped", "rtt_ms"}
    - Server → Client: {"type": "pause_requested"|"resume_requested",
      "generation"} — pending acks only, NOT confirmed control changes
    - Client → Server: {"type": "frame_ack", "seq": N}
    - Client → Server: {"type": "takeover_accept"}
    - Client → Server: {"type": "takeover_reject"}
    - Client → Server: {"type": "return_control"}
    - Client → Server: {"type": "takeover_heartbeat", "lease_id"}
    - Client → Server: {"type": "input", "kind": "click", "x": 100, "y": 200}
    - Client → Server: {"type": "input", "kind": "type", "text": "hello"}
    - Client → Server: {"type": "nav", "kind": "back"|"forward"|"reload"}
    """
    await websocket.accept()
    try:
        auth_text = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        auth_message = json.loads(auth_text)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, TypeError):
        await websocket.close(code=4001, reason="Unauthorized")
        return
    raw_ticket = (
        auth_message.get("ticket")
        if isinstance(auth_message, dict) and auth_message.get("type") == "authenticate"
        else None
    )
    user_id = consume_ws_ticket(raw_ticket) if isinstance(raw_ticket, str) else None

    if not user_id:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if not await _verify_execution_access(execution_id, user_id, db=db):
        await websocket.close(code=4003, reason="Forbidden")
        return

    _viewport_connections[execution_id] = websocket
    logger.info("Viewport connected for execution %s (user %s)", execution_id, user_id)

    relay = FrameRelay()
    pump_task = asyncio.create_task(_pump_loop(execution_id, websocket, relay))

    # Send current authoritative control state immediately (with lease info so a
    # reconnecting client can resume its heartbeat without losing state).
    active_lease_id: str | None = None
    try:
        rec = await get_control_record(execution_id)
        active_lease_id = rec.lease_id if rec.state == ControlState.HUMAN_CONTROL else None
        lease_expires = rec.lease_expires_at
        if lease_expires is not None and hasattr(lease_expires, "isoformat"):
            lease_expires = lease_expires.isoformat()
        await websocket.send_json({
            "type": "control_changed",
            "control": derive_control_value(rec.state),
            "state": rec.state.value if hasattr(rec.state, "value") else str(rec.state),
            "generation": rec.generation,
            "lease_id": active_lease_id,
            "lease_expires_at": lease_expires,
            "checkpoint": rec.checkpoint,
        })
    except Exception:
        pass
    await websocket.send_json({"type": "masking_status", "masking": "unknown"})

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "frame_ack":
                try:
                    relay.settle_up_to(int(msg.get("seq", 0)))
                except (TypeError, ValueError):
                    pass

            if msg_type in ("takeover_accept", "takeover", "acquire_control"):
                ok, lease_or_err, rec = await acquire_human_takeover(execution_id, client_id=str(user_id))
                if ok:
                    active_lease_id = lease_or_err
                    # QUIESCING means the lease is reserved but human input is
                    # not yet accepted — an explicitly pending state, not a
                    # confirmed "You have control".
                    await websocket.send_json({
                        "type": "takeover_granted",
                        "lease_id": active_lease_id,
                        "generation": rec.generation,
                        "control": derive_control_value(rec.state),
                        "state": rec.state.value,
                    })
                    await websocket.send_json({
                        "type": "control_changed",
                        "control": derive_control_value(rec.state),
                        "state": rec.state.value,
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
                await websocket.send_json({"type": "control_error", "reason": "Client declined takeover"})
                logger.info("User takeover rejected by client for %s", execution_id)

            elif msg_type in ("takeover_heartbeat", "lease_heartbeat", "heartbeat"):
                lease = msg.get("lease_id") or active_lease_id
                ok, lease_or_err, rec = await renew_human_control_lease(
                    execution_id,
                    client_id=str(user_id),
                    lease_id=lease,
                )
                if ok:
                    active_lease_id = lease_or_err or active_lease_id
                    await websocket.send_json({
                        "type": "lease_renewed",
                        "lease_id": active_lease_id,
                        "expires_at": rec.lease_expires_at,
                        "generation": rec.generation,
                    })
                else:
                    active_lease_id = None
                    await websocket.send_json({
                        "type": "lease_expired",
                        "reason": lease_or_err,
                    })
                    logger.info("Lease renewal failed for %s: %s", execution_id, lease_or_err)

            elif msg_type in ("return_control", "release_control"):
                lease = msg.get("lease_id") or active_lease_id
                ok, err, rec = await release_human_control(execution_id, client_id=str(user_id), lease_id=lease)
                if ok:
                    active_lease_id = None
                    logger.info("User returned control for %s", execution_id)
                else:
                    # Release failed — the client keeps showing the confirmed
                    # state; the control poll will correct it if it changes.
                    await websocket.send_json({"type": "control_error", "reason": err})

            elif msg_type == "pause":
                rec = await request_pause(execution_id, reason="User requested pause via live view")
                # Pending ack only: PAUSE_REQUESTED is not 'paused'. The
                # confirmed state arrives via the control poll when the record
                # actually reaches PAUSED.
                await websocket.send_json({
                    "type": "pause_requested",
                    "control": derive_control_value(rec.state),
                    "state": rec.state.value,
                    "generation": rec.generation,
                })

            elif msg_type == "resume":
                rec = await request_resume(execution_id)
                await websocket.send_json({
                    "type": "resume_requested",
                    "control": derive_control_value(rec.state),
                    "state": rec.state.value,
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
