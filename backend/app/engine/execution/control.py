"""Authoritative execution control state machine, lease management, and cross-process channel.

Supports:
- Authoritative control states: RUNNING, PAUSE_REQUESTED, PAUSED, HUMAN_CONTROL, RESUME_REQUESTED, and terminal states.
- Monotonic generation counter to reject stale or delayed commands.
- Exclusive human takeover lease: only one human actor holds the lease.
- Concurrency safety: atomic transitions, stop/cancel priority over pause/resume.
- Human checkpoint management for authentication barriers (CAPTCHA, MFA, consent).
- Dual transport: Redis pub/sub across worker processes, with in-memory threadsafe fallback
  when Redis is unavailable.
"""

from __future__ import annotations

import asyncio
import ssl
import enum
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from app.config.settings import settings

logger = logging.getLogger(__name__)


class ControlState(str, enum.Enum):
    RUNNING = "RUNNING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    QUIESCING = "QUIESCING"
    HUMAN_CONTROL = "HUMAN_CONTROL"
    RECONCILING = "RECONCILING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    RESUME_REQUESTED = "RESUME_REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"


# Normalize aliases
CONTROL_ALIASES: dict[str, ControlState] = {
    "agent": ControlState.RUNNING,
    "running": ControlState.RUNNING,
    "pause_requested": ControlState.PAUSE_REQUESTED,
    "paused": ControlState.PAUSED,
    "human": ControlState.HUMAN_CONTROL,
    "human_control": ControlState.HUMAN_CONTROL,
    "human_controlled": ControlState.HUMAN_CONTROL,
    "user_control": ControlState.HUMAN_CONTROL,
    "quiescing": ControlState.QUIESCING,
    "reconciling": ControlState.RECONCILING,
    "waiting_for_user": ControlState.WAITING_FOR_USER,
    "waitingforuser": ControlState.WAITING_FOR_USER,
    "resuming": ControlState.RESUME_REQUESTED,
    "resume_requested": ControlState.RESUME_REQUESTED,
    "completed": ControlState.COMPLETED,
    "failed": ControlState.FAILED,
    "cancelled": ControlState.CANCELLED,
    "blocked": ControlState.BLOCKED,
    "unverified": ControlState.UNVERIFIED,
}

TERMINAL_CONTROL_STATES: set[ControlState] = {
    ControlState.COMPLETED,
    ControlState.FAILED,
    ControlState.CANCELLED,
    ControlState.TIMEOUT,
    ControlState.BLOCKED,
    ControlState.UNVERIFIED,
}


@dataclass
class ControlRecord:
    execution_id: str
    state: ControlState = ControlState.RUNNING
    owner: str = "agent"  # "agent" or client_id/user_id
    lease_id: str | None = None
    lease_expires_at: float | None = None
    generation: int = 1
    checkpoint: dict[str, Any] | None = None
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "state": self.state.value if isinstance(self.state, ControlState) else str(self.state),
            "owner": self.owner,
            "lease_id": self.lease_id,
            "lease_expires_at": self.lease_expires_at,
            "generation": self.generation,
            "checkpoint": self.checkpoint,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControlRecord":
        raw_state = data.get("state", "RUNNING")
        norm_state = (
            CONTROL_ALIASES.get(str(raw_state).lower())
            or (ControlState(raw_state) if raw_state in ControlState.__members__ else ControlState.RUNNING)
        )
        return cls(
            execution_id=str(data.get("execution_id", "")),
            state=norm_state,
            owner=str(data.get("owner", "agent")),
            lease_id=data.get("lease_id"),
            lease_expires_at=data.get("lease_expires_at"),
            generation=int(data.get("generation", 1)),
            checkpoint=data.get("checkpoint"),
            updated_at=float(data.get("updated_at", time.time())),
        )


CONTROL_PREFIX = "kova:control"
COMMAND_CHANNEL = f"{CONTROL_PREFIX}:commands"
STATE_KEY_PREFIX = f"{CONTROL_PREFIX}:state"
INPUT_KEY_PREFIX = f"{CONTROL_PREFIX}:input"
CANCELLED_KEY_PREFIX = f"{CONTROL_PREFIX}:cancelled"
FAIL_ON_HEALED_KEY_PREFIX = f"{CONTROL_PREFIX}:fail_on_healed"

# In-memory storage and broadcast fallbacks for tests or when Redis is absent
_memory_records: dict[str, ControlRecord] = {}
_memory_inputs: dict[str, list[dict[str, Any]]] = {}
_memory_cancelled: set[str] = set()
_memory_fail_on_healed: set[str] = set()
_memory_command_subscribers: dict[str, set[asyncio.Queue]] = {}
_control_locks: dict[str, asyncio.Lock] = {}

_redis: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None
_redis_checked: bool = False
_redis_available: bool = False
_last_redis_check: float = 0.0


def _get_control_lock(execution_id: str) -> asyncio.Lock:
    if execution_id not in _control_locks:
        _control_locks[execution_id] = asyncio.Lock()
    return _control_locks[execution_id]


async def _get_redis() -> aioredis.Redis | None:
    """Return a fast, verified Redis client or None if Redis is not running."""
    global _redis, _redis_loop, _redis_checked, _redis_available, _last_redis_check
    loop = asyncio.get_running_loop()

    if _redis is not None and _redis_loop is not None and _redis_loop is not loop:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None
        _redis_loop = None
        _redis_checked = False

    if _redis is not None and _redis_available:
        return _redis

    now = time.time()
    if _redis_checked and not _redis_available and (now - _last_redis_check < 2.0):
        return None

    _last_redis_check = now
    try:
        kwargs: dict[str, Any] = {
            "decode_responses": True,
            "socket_connect_timeout": 3.0,
            "socket_timeout": 3.0,
        }
        if settings.REDIS_URL.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = "none"
        client = aioredis.from_url(settings.REDIS_URL, **kwargs)
        await asyncio.wait_for(client.ping(), timeout=3.0)
        _redis = client
        _redis_loop = loop
        _redis_checked = True
        _redis_available = True
        return _redis
    except Exception as exc:
        logger.debug("Redis unavailable for control channel; using in-memory store: %s", exc)
        _redis_checked = True
        _redis_available = False
        return None




def _state_key(execution_id: str) -> str:
    return f"{STATE_KEY_PREFIX}:{execution_id}"


def _input_key(execution_id: str) -> str:
    return f"{INPUT_KEY_PREFIX}:{execution_id}"


def _cancelled_key(execution_id: str) -> str:
    return f"{CANCELLED_KEY_PREFIX}:{execution_id}"


def _fail_on_healed_key(execution_id: str) -> str:
    return f"{FAIL_ON_HEALED_KEY_PREFIX}:{execution_id}"


# ── Authoritative Record Operations ───────────────────────────────────


async def get_control_record(execution_id: str) -> ControlRecord:
    """Retrieve current authoritative control record for execution."""
    r = await _get_redis()
    if r is not None:
        try:
            raw = await r.get(_state_key(execution_id))
            if raw:
                data = json.loads(raw)
                return ControlRecord.from_dict(data)
        except Exception as e:
            logger.debug("Redis get_control_record failed: %s", e)

    # Fallback to memory
    record = _memory_records.get(execution_id)
    if not record:
        record = ControlRecord(execution_id=execution_id)
        _memory_records[execution_id] = ControlRecord.from_dict(record.to_dict())
    return ControlRecord.from_dict(record.to_dict())


async def save_control_record(record: ControlRecord) -> None:
    """Save control record to Redis and/or in-memory cache."""
    record.updated_at = time.time()
    payload = json.dumps(record.to_dict())

    _memory_records[record.execution_id] = ControlRecord.from_dict(record.to_dict())


    r = await _get_redis()
    if r is not None:
        try:
            await r.set(_state_key(record.execution_id), payload, ex=1800)
        except Exception as e:
            logger.debug("Redis save_control_record failed: %s", e)


# ── State Machine & Concurrency Control (Feature B & C) ───────────────


async def request_pause(execution_id: str, requester: str = "user", reason: str = "") -> ControlRecord:
    """Request a safe pause. Transitions RUNNING -> PAUSE_REQUESTED.

    If already PAUSED or HUMAN_CONTROL, leaves state unchanged.
    Terminal states reject pause.
    """
    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)
        if record.state in TERMINAL_CONTROL_STATES:
            logger.warning("Cannot pause execution %s in terminal state %s", execution_id, record.state)
            return record

        if record.state in (ControlState.PAUSED, ControlState.HUMAN_CONTROL):
            return record

        record.state = ControlState.PAUSE_REQUESTED
        record.generation += 1
        await save_control_record(record)
        await publish_command(execution_id, "pause", requester=requester, reason=reason, generation=record.generation)
        return record


async def confirm_paused(execution_id: str) -> ControlRecord:
    """Worker acknowledges agent actions have stopped and execution is at safe boundary."""
    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)
        if record.state in TERMINAL_CONTROL_STATES:
            return record

        record.state = ControlState.PAUSED
        record.generation += 1
        await save_control_record(record)
        await publish_command(execution_id, "paused_confirmed", generation=record.generation)
        return record


async def acquire_human_takeover(
    execution_id: str,
    client_id: str,
    lease_duration_seconds: float = 300.0,
    lease_ttl_seconds: float | None = None,
) -> tuple[bool, str, ControlRecord]:
    """Acquire exclusive human control of the browser session.

    Enforces exclusive ownership:
    - If another human already owns control, returns (False, error, record).
    - If running, immediately transitions to PAUSE_REQUESTED and initiates safe takeover.
    - Issues a unique lease_id and advances the generation counter.
    """
    if lease_ttl_seconds is not None:
        lease_duration_seconds = lease_ttl_seconds

    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)

        if record.state in TERMINAL_CONTROL_STATES:
            return False, f"Execution is in terminal state ({record.state.value})", record

        # Check if already held by another client
        now = time.time()
        if record.state == ControlState.HUMAN_CONTROL:
            if record.owner == client_id:
                # Same client renewing lease
                record.lease_expires_at = now + lease_duration_seconds
                record.updated_at = now
                await save_control_record(record)
                return True, record.lease_id or "", record
            # Competing client attempting takeover
            if record.lease_expires_at and now < record.lease_expires_at:
                return False, f"Browser control is exclusively held by another session ({record.owner})", record

        # Grant takeover
        lease_id = f"lease_{uuid.uuid4().hex[:12]}"
        record.state = ControlState.HUMAN_CONTROL
        record.owner = client_id
        record.lease_id = lease_id
        record.lease_expires_at = now + lease_duration_seconds
        record.generation += 1
        await save_control_record(record)

        await publish_command(
            execution_id,
            "human_takeover_granted",
            client_id=client_id,
            lease_id=lease_id,
            generation=record.generation,
        )
        return True, lease_id, record



async def release_human_control(
    execution_id: str,
    client_id: str | None = None,
    lease_id: str | None = None,
) -> tuple[bool, str, ControlRecord]:
    """Release human control lease and transition to RESUME_REQUESTED.

    Validates lease ownership if provided.
    """
    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)

        if record.state in TERMINAL_CONTROL_STATES:
            return False, "Execution already terminated", record

        if record.state not in (ControlState.HUMAN_CONTROL, ControlState.PAUSED, ControlState.PAUSE_REQUESTED):
            return False, f"Execution not in human control or paused (currently {record.state.value})", record

        if lease_id and record.lease_id and record.lease_id != lease_id:
            return False, "Mismatched or stale lease ID", record

        record.state = ControlState.RESUME_REQUESTED
        record.owner = "agent"
        record.lease_id = None
        record.lease_expires_at = None
        record.generation += 1
        await save_control_record(record)

        await publish_command(
            execution_id,
            "resume",
            generation=record.generation,
        )
        return True, "Control returned to agent", record



async def request_resume(execution_id: str) -> ControlRecord:
    """Request resuming execution back to agent control."""
    success, _, record = await release_human_control(execution_id)
    return record


async def confirm_resumed(execution_id: str) -> ControlRecord:
    """Runner confirms browser re-observation is complete and agent has resumed RUNNING."""
    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)
        if record.state in TERMINAL_CONTROL_STATES:
            return record

        record.state = ControlState.RUNNING
        record.owner = "agent"
        record.lease_id = None
        record.generation += 1
        await save_control_record(record)
        return record


# ── Human Checkpoints for Auth Barriers (Feature D) ───────────────────


async def raise_human_checkpoint(
    execution_id: str,
    checkpoint_type: str = "human_intervention_required",
    description: str = "",
    details: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> ControlRecord:
    """Raise a human checkpoint (CAPTCHA, MFA, consent wall) and park the runner.

    Transitions to PAUSED with structured checkpoint details.
    """
    if checkpoint is not None:
        checkpoint_type = checkpoint.get("type", checkpoint_type)
        description = checkpoint.get("description", description)
        details = checkpoint.get("details", details or {})

    async with _get_control_lock(execution_id):

        record = await get_control_record(execution_id)
        if record.state in TERMINAL_CONTROL_STATES:
            return record

        record.state = ControlState.PAUSED
        cp_dict: dict[str, Any] = {
            "type": checkpoint_type,
            "description": description,
            "details": details or {},
            "raised_at": time.time(),
        }
        if checkpoint:
            cp_dict.update(checkpoint)
            cp_dict["raised_at"] = cp_dict.get("raised_at", time.time())
        record.checkpoint = cp_dict
        record.generation += 1

        await save_control_record(record)

        await publish_command(
            execution_id,
            "human_checkpoint",
            checkpoint_type=checkpoint_type,
            description=description,
            generation=record.generation,
        )
        return record


async def resolve_human_checkpoint(execution_id: str) -> ControlRecord:
    """Clear active checkpoint upon human intervention."""
    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)
        record.checkpoint = None
        record.generation += 1
        await save_control_record(record)
        return record


# ── Cancellation & Stop ────────────────────────────────────────────────


async def request_cancel(execution_id: str, reason: str = "") -> None:
    """Request cancellation of a running execution. Stop has top priority over pause/resume."""
    async with _get_control_lock(execution_id):
        _memory_cancelled.add(execution_id)
        r = await _get_redis()
        if r is not None:
            try:
                await r.set(_cancelled_key(execution_id), "1", ex=1800)
            except Exception as e:
                logger.debug("Redis request_cancel failed: %s", e)

        record = await get_control_record(execution_id)
        record.state = ControlState.CANCELLED
        record.owner = "none"
        record.lease_id = None
        record.generation += 1
        await save_control_record(record)

        await publish_command(execution_id, "cancel", reason=reason, generation=record.generation)


async def is_cancel_requested(execution_id: str) -> bool:
    """Check whether cancellation has been requested for this execution."""
    if execution_id in _memory_cancelled:
        return True
    r = await _get_redis()
    if r is not None:
        try:
            return bool(await r.get(_cancelled_key(execution_id)))
        except Exception:
            pass
    return False


# Backwards compatibility / convenience aliases
request_cancellation = request_cancel
is_cancelled = is_cancel_requested



# ── Concurrency Safe Input Validation ─────────────────────────────────


async def validate_human_interaction(
    execution_id: str,
    lease_id: str | None = None,
    client_id: str | None = None,
    command_generation: int | None = None,
    generation: int | None = None,
) -> tuple[bool, str | None]:
    """Validate whether an incoming human interaction is authorized and current.

    Rejects:
    - If execution is not in HUMAN_CONTROL.
    - If lease_id does not match the active lease.
    - If command_generation is stale.
    - If lease has expired.
    """
    if generation is not None and command_generation is None:
        command_generation = generation

    record = await get_control_record(execution_id)

    if record.state != ControlState.HUMAN_CONTROL:
        return False, f"Cannot interact: execution is in {record.state.value} state (not HUMAN_CONTROL)"

    if record.lease_expires_at and time.time() > record.lease_expires_at:
        return False, "Human control lease has expired"

    if lease_id and record.lease_id and record.lease_id != lease_id:
        return False, "Stale or invalid lease ID"

    if client_id and record.owner != "agent" and record.owner != client_id:
        return False, f"Control held by another client ({record.owner})"

    if command_generation is not None and command_generation < record.generation:
        return False, f"Stale command generation ({command_generation} < {record.generation})"

    return True, None



# ── Input Queueing & Draining ──────────────────────────────────────────


async def queue_user_input(execution_id: str, input_msg: dict[str, Any]) -> None:
    """Queue human interaction message for the runner to execute."""
    r = await _get_redis()
    if r is not None:
        try:
            await r.rpush(_input_key(execution_id), json.dumps(input_msg))
            await r.expire(_input_key(execution_id), 600)
            return
        except Exception as e:
            logger.debug("Redis queue_user_input failed: %s", e)

    if execution_id not in _memory_inputs:
        _memory_inputs[execution_id] = []
    _memory_inputs[execution_id].append(input_msg)


async def queue_worker_input(execution_id: str, input_msg: dict[str, Any]) -> None:
    """Queue a durable worker signal; fail closed if shared Redis is unavailable."""
    r = await _get_redis()
    if r is None:
        raise RuntimeError("Shared worker control channel is unavailable")
    key = _input_key(execution_id)
    await r.rpush(key, json.dumps(input_msg))
    await r.expire(key, 600)


async def get_pending_input(execution_id: str) -> list[dict[str, Any]]:
    """Pop and return all queued human interaction messages."""
    items: list[dict[str, Any]] = []

    r = await _get_redis()
    if r is not None:
        try:
            key = _input_key(execution_id)
            while True:
                raw = await r.lpop(key)
                if raw is None:
                    break
                try:
                    items.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
            if items:
                return items
        except Exception as e:
            logger.debug("Redis get_pending_input failed: %s", e)

    mem_items = _memory_inputs.pop(execution_id, [])
    return items or mem_items


# ── Backward-Compatible Aliases ────────────────────────────────────────


async def set_control_state(execution_id: str, state: str) -> None:
    """Legacy helper: set control state."""
    norm = CONTROL_ALIASES.get(state.lower()) or ControlState.RUNNING
    async with _get_control_lock(execution_id):
        record = await get_control_record(execution_id)
        record.state = norm
        record.owner = "human" if norm == ControlState.HUMAN_CONTROL else "agent"
        record.generation += 1
        await save_control_record(record)


async def get_control_state(execution_id: str) -> str:
    """Legacy helper: get control state as lowercase string ('agent'|'human'|'paused')."""
    record = await get_control_record(execution_id)
    if record.state == ControlState.HUMAN_CONTROL:
        return "human"
    if record.state in (ControlState.PAUSED, ControlState.PAUSE_REQUESTED):
        return "paused"
    if record.state == ControlState.RESUME_REQUESTED:
        return "resuming"
    return "agent"


async def check_pause(execution_id: str) -> bool:
    """Check if execution should pause or enter human control."""
    record = await get_control_record(execution_id)
    return record.state in (ControlState.PAUSE_REQUESTED, ControlState.PAUSED, ControlState.HUMAN_CONTROL)


async def wait_for_resume(execution_id: str, timeout: float = 300.0) -> bool:
    """Block until control state returns to agent."""
    record = await get_control_record(execution_id)
    if record.state == ControlState.RUNNING:
        return True

    start = time.time()
    while time.time() - start < timeout:
        rec = await get_control_record(execution_id)
        if rec.state == ControlState.RUNNING:
            return True
        await asyncio.sleep(0.2)
    return False


async def publish_command(execution_id: str, command: str, **data: Any) -> None:
    """Publish a control command to subscribers (Redis and local queues)."""
    payload_dict = {"command": command, **data}
    payload_str = json.dumps(payload_dict)

    # Deliver to local queues
    if execution_id in _memory_command_subscribers:
        for q in list(_memory_command_subscribers[execution_id]):
            try:
                q.put_nowait(payload_dict)
            except Exception:
                pass

    r = await _get_redis()
    if r is not None:
        try:
            await r.publish(f"{COMMAND_CHANNEL}:{execution_id}", payload_str)
        except Exception as e:
            logger.debug("Redis publish_command failed: %s", e)


async def publish_worker_command(execution_id: str, command: str, **data: Any) -> None:
    """Publish commands that must reach a remote worker; do not use local fallback."""
    r = await _get_redis()
    if r is None:
        raise RuntimeError("Shared worker control channel is unavailable")
    await r.publish(
        f"{COMMAND_CHANNEL}:{execution_id}",
        json.dumps({"command": command, **data}),
    )


async def subscribe_commands(execution_id: str) -> AsyncIterator[dict[str, Any]]:
    """Subscribe to control commands. Yields command dictionaries."""
    local_q: asyncio.Queue = asyncio.Queue()
    if execution_id not in _memory_command_subscribers:
        _memory_command_subscribers[execution_id] = set()
    _memory_command_subscribers[execution_id].add(local_q)

    r = await _get_redis()
    if r is not None:
        pubsub = r.pubsub()
        await pubsub.subscribe(f"{COMMAND_CHANNEL}:{execution_id}")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        yield json.loads(message["data"])
                    except json.JSONDecodeError:
                        pass
        finally:
            try:
                await pubsub.unsubscribe(f"{COMMAND_CHANNEL}:{execution_id}")
                await pubsub.aclose()
            except Exception:
                pass
            _memory_command_subscribers.get(execution_id, set()).discard(local_q)
    else:
        # In-memory queue loop
        try:
            while True:
                msg = await local_q.get()
                yield msg
        finally:
            _memory_command_subscribers.get(execution_id, set()).discard(local_q)


async def set_execution_fail_on_healed(execution_id: str, fail_on_healed: bool) -> None:
    if fail_on_healed:
        _memory_fail_on_healed.add(execution_id)
    else:
        _memory_fail_on_healed.discard(execution_id)
    r = await _get_redis()
    if r is not None:
        try:
            key = _fail_on_healed_key(execution_id)
            if fail_on_healed:
                await r.set(key, "1", ex=3600)
            else:
                await r.delete(key)
        except Exception:
            pass


async def get_execution_fail_on_healed(execution_id: str) -> bool:
    if execution_id in _memory_fail_on_healed:
        return True
    r = await _get_redis()
    if r is not None:
        try:
            val = await r.get(_fail_on_healed_key(execution_id))
            return val == "1"
        except Exception:
            pass
    return False


async def cleanup_control(execution_id: str) -> None:
    """Clean up all control resources for an execution."""
    _memory_records.pop(execution_id, None)
    _memory_inputs.pop(execution_id, None)
    _memory_cancelled.discard(execution_id)
    _memory_fail_on_healed.discard(execution_id)
    _memory_command_subscribers.pop(execution_id, None)
    _control_locks.pop(execution_id, None)

    r = await _get_redis()
    if r is not None:
        try:
            await r.delete(_state_key(execution_id))
            await r.delete(_input_key(execution_id))
            await r.delete(_cancelled_key(execution_id))
            await r.delete(_fail_on_healed_key(execution_id))
        except Exception:
            pass
