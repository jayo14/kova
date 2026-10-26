"""Unit tests for authoritative execution control state machine, leases, and input validation."""

import asyncio
import time
import pytest

from app.engine.execution.control import (
    ControlState,
    ControlRecord,
    TERMINAL_CONTROL_STATES,
    get_control_record,
    set_control_state,
    request_pause,
    confirm_paused,
    acquire_human_takeover,
    release_human_control,
    request_resume,
    confirm_resumed,
    validate_human_interaction,
    queue_user_input,
    get_pending_input,
    raise_human_checkpoint,
    resolve_human_checkpoint,
    check_pause,
    is_cancelled,
    request_cancellation,
    cleanup_control,
)


@pytest.mark.asyncio
async def test_control_lifecycle_normal_flow():
    exec_id = "test-exec-normal-1"
    await cleanup_control(exec_id)

    # 1. Initial state
    rec = await get_control_record(exec_id)
    assert rec.state == ControlState.RUNNING
    assert rec.owner == "agent"
    assert rec.lease_id is None
    assert rec.generation >= 1

    # 2. Request pause
    rec_pause = await request_pause(exec_id, reason="User requested pause")
    assert rec_pause.state == ControlState.PAUSE_REQUESTED
    assert rec_pause.generation > rec.generation

    # 3. Confirm paused by runner
    rec_paused = await confirm_paused(exec_id)
    assert rec_paused.state == ControlState.PAUSED
    assert rec_paused.generation > rec_pause.generation

    # Check pause helper returns True
    assert await check_pause(exec_id) is True

    # 4. Request resume
    rec_resume = await request_resume(exec_id)
    assert rec_resume.state == ControlState.RESUME_REQUESTED
    assert rec_resume.generation > rec_paused.generation

    # 5. Confirm resumed by runner
    rec_running = await confirm_resumed(exec_id)
    assert rec_running.state == ControlState.RUNNING
    assert rec_running.owner == "agent"
    assert rec_running.lease_id is None
    assert rec_running.generation > rec_resume.generation
    assert await check_pause(exec_id) is False

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_human_takeover_exclusive_lease():
    exec_id = "test-exec-takeover-lease"
    await cleanup_control(exec_id)

    # Initial state
    await confirm_paused(exec_id)

    # Client A acquires takeover
    ok_a, lease_a, rec_a = await acquire_human_takeover(exec_id, client_id="user-alice", lease_ttl_seconds=5)
    assert ok_a is True
    assert lease_a is not None
    assert rec_a.state == ControlState.HUMAN_CONTROL
    assert rec_a.owner == "user-alice"
    assert rec_a.lease_id == lease_a
    assert rec_a.lease_expires_at is not None
    assert rec_a.lease_expires_at > time.time()

    # Competing client B attempts takeover while lease A is active -> rejected
    ok_b, lease_b, rec_b = await acquire_human_takeover(exec_id, client_id="user-bob", lease_ttl_seconds=5)
    assert ok_b is False
    assert rec_b.owner == "user-alice"
    assert rec_b.lease_id == lease_a

    # Same client A re-acquiring or refreshing lease -> succeeds
    ok_a2, lease_a2, rec_a2 = await acquire_human_takeover(exec_id, client_id="user-alice", lease_ttl_seconds=10)
    assert ok_a2 is True
    assert lease_a2 is not None
    assert rec_a2.owner == "user-alice"

    # User Alice validates interaction
    is_valid, err = await validate_human_interaction(exec_id, lease_id=lease_a2, generation=rec_a2.generation)
    assert is_valid is True
    assert err is None

    # Stale generation is rejected
    is_valid_stale, err_stale = await validate_human_interaction(exec_id, lease_id=lease_a2, generation=rec_a2.generation - 1)
    assert is_valid_stale is False
    assert "stale" in err_stale.lower()

    # Invalid lease is rejected
    is_valid_fake, err_fake = await validate_human_interaction(exec_id, lease_id="fake-lease-token", generation=rec_a2.generation)
    assert is_valid_fake is False
    assert "lease" in err_fake.lower()

    # Competing client B trying to release A's lease -> rejected
    released_b, err_b, _ = await release_human_control(exec_id, lease_id="bad-lease")
    assert released_b is False
    assert "lease" in err_b.lower()

    # Alice releases control -> returns control to agent
    released_a, msg_a, rec_released = await release_human_control(exec_id, lease_id=lease_a2)
    assert released_a is True
    assert rec_released.state == ControlState.RESUME_REQUESTED
    assert rec_released.lease_id is None

    await cleanup_control(exec_id)



@pytest.mark.asyncio
async def test_human_takeover_lease_expiration():
    exec_id = "test-exec-lease-expiry"
    await cleanup_control(exec_id)

    # Client A acquires takeover with 0.1s TTL
    ok_a, lease_a, rec_a = await acquire_human_takeover(exec_id, client_id="user-alice", lease_ttl_seconds=0.1)
    assert ok_a is True
    assert lease_a is not None
    assert rec_a.state == ControlState.HUMAN_CONTROL

    # Wait for lease to expire
    await asyncio.sleep(0.15)

    # Client A's interaction is now rejected due to lease expiry
    is_valid, err = await validate_human_interaction(exec_id, lease_id=lease_a, generation=rec_a.generation)
    assert is_valid is False
    assert "expired" in err.lower()

    # Client B can now acquire takeover since lease A expired
    ok_b, lease_b, rec_b = await acquire_human_takeover(exec_id, client_id="user-bob", lease_ttl_seconds=5)
    assert ok_b is True
    assert lease_b is not None
    assert rec_b.owner == "user-bob"
    assert rec_b.lease_id == lease_b

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_terminal_states_prevent_takeover_and_resume():
    exec_id = "test-exec-terminal"
    await cleanup_control(exec_id)

    # Cancel execution
    await request_cancellation(exec_id)
    assert await is_cancelled(exec_id) is True

    # Attempt to request pause on cancelled execution -> remains CANCELLED
    rec_pause = await request_pause(exec_id)
    assert rec_pause.state == ControlState.CANCELLED

    # Attempt to acquire takeover on cancelled execution -> rejected
    ok_t, lease_t, rec_takeover = await acquire_human_takeover(exec_id, client_id="user-alice")
    assert ok_t is False
    assert lease_t is not None
    assert rec_takeover.state == ControlState.CANCELLED

    # Attempt to resume cancelled execution -> rejected
    rec_resume = await request_resume(exec_id)
    assert rec_resume.state == ControlState.CANCELLED

    await cleanup_control(exec_id)



@pytest.mark.asyncio
async def test_human_checkpoint_handling():
    exec_id = "test-exec-checkpoint"
    await cleanup_control(exec_id)

    # Raise checkpoint (e.g. CAPTCHA or MFA detected)
    checkpoint_data = {
        "type": "captcha_detected",
        "description": "Cloudflare Turnstile challenge present on page",
        "url": "https://example.com/login",
    }
    rec_cp = await raise_human_checkpoint(exec_id, checkpoint=checkpoint_data)
    assert rec_cp.state == ControlState.PAUSED
    assert rec_cp.checkpoint is not None
    assert rec_cp.checkpoint["type"] == checkpoint_data["type"]
    assert rec_cp.checkpoint["description"] == checkpoint_data["description"]
    assert rec_cp.checkpoint["url"] == checkpoint_data["url"]
    assert "raised_at" in rec_cp.checkpoint

    # Verify get_control_record returns checkpoint
    rec_read = await get_control_record(exec_id)
    assert rec_read.checkpoint is not None
    assert rec_read.checkpoint["type"] == "captcha_detected"

    # Human acquires control, solves it, and releases control
    ok_takeover, lease, _ = await acquire_human_takeover(exec_id, client_id="operator")
    assert ok_takeover is True
    assert lease is not None

    assert lease is not None

    # Resolve checkpoint
    rec_res = await resolve_human_checkpoint(exec_id)
    assert rec_res.checkpoint is None

    rec_res_read = await get_control_record(exec_id)
    assert rec_res_read.checkpoint is None

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_input_queue_and_drain():
    exec_id = "test-exec-input-q"
    await cleanup_control(exec_id)

    # Queue inputs
    await queue_user_input(exec_id, {"type": "click", "x": 100, "y": 200})
    await queue_user_input(exec_id, {"type": "type", "text": "hello"})

    # Drain inputs
    inputs = await get_pending_input(exec_id)
    assert len(inputs) == 2
    assert inputs[0]["type"] == "click"
    assert inputs[1]["text"] == "hello"

    # Second drain is empty
    inputs_empty = await get_pending_input(exec_id)
    assert len(inputs_empty) == 0

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_validate_interaction_state_guards():
    exec_id = "test-exec-guards"
    await cleanup_control(exec_id)

    # 1. Reject interaction when RUNNING
    valid, err = await validate_human_interaction(exec_id, lease_id="any", generation=1)
    assert valid is False
    assert "RUNNING" in err

    # 2. Reject interaction when PAUSED (must acquire takeover first)
    await confirm_paused(exec_id)
    valid, err = await validate_human_interaction(exec_id, lease_id="any", generation=2)
    assert valid is False
    assert "PAUSED" in err

    # 3. Acquire takeover
    ok, lease, rec = await acquire_human_takeover(exec_id, client_id="alice")
    assert ok is True

    # 4. Reject interaction if client_id does not match
    valid, err = await validate_human_interaction(exec_id, lease_id=lease, client_id="bob", generation=rec.generation)
    assert valid is False
    assert "another client" in err

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_command_pubsub_dispatch():
    exec_id = "test-exec-pubsub"
    await cleanup_control(exec_id)

    from app.engine.execution.control import subscribe_commands, publish_command

    received = []

    async def listener():
        async for cmd in subscribe_commands(exec_id):
            received.append(cmd)
            if len(received) >= 2:
                break

    task = asyncio.create_task(listener())
    await asyncio.sleep(0.05)

    await publish_command(exec_id, "pause", reason="test")
    await publish_command(exec_id, "resume")

    await asyncio.wait_for(task, timeout=2.0)
    assert len(received) == 2
    assert received[0]["command"] == "pause"
    assert received[1]["command"] == "resume"

    await cleanup_control(exec_id)
