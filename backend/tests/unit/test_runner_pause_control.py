"""Unit tests for FlowRunner authoritative pause gate and post-takeover adaptive re-planning."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.engine.execution.context import ExecutionContext
from app.engine.execution.control import (
    ControlState,
    cleanup_control,
    request_pause,
    request_cancel,
    request_resume,
    acquire_human_takeover,
    release_human_control,
    raise_human_checkpoint,
    get_control_record,
)
from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState
from app.modules.executions.event_types import EventTypes


@pytest.mark.asyncio
async def test_runner_pause_and_adaptive_resume():
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=exec_id, target_url="https://example.com")
    ctx.state = ExecutionState.RUNNING

    browser = MagicMock()
    browser.page = AsyncMock()
    browser.page.url = "https://example.com/login"
    browser.page.screenshot = AsyncMock(return_value=b"fake-jpeg")
    browser.observe = AsyncMock(return_value={"title": "Dashboard", "elements": []})

    recorded_events = []

    async def event_recorder(eid, event_type, payload):
        recorded_events.append((event_type, payload))

    # 1. Request pause
    await request_pause(exec_id)

    # Background task waits until runner is confirmed in PAUSED, then releases control
    async def release_when_paused():
        for _ in range(100):
            rec = await get_control_record(exec_id)
            if rec.state == ControlState.PAUSED:
                break
            await asyncio.sleep(0.01)
        # Simulate user logged in during takeover: page navigated to /dashboard
        browser.page.url = "https://example.com/dashboard"
        await release_human_control(exec_id)

    resume_task = asyncio.create_task(release_when_paused())

    handled = await runner._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
    await resume_task

    assert handled is True
    assert ctx.current_state.get("authenticated") is True
    assert ctx.current_state.get("auth_restored") is True

    # Verify observe was called adaptively after resume
    browser.observe.assert_called_once()

    # Verify authoritative control record returned to agent
    rec = await get_control_record(exec_id)
    assert rec.state == ControlState.RUNNING
    assert rec.owner == "agent"

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_runner_cancellation_during_pause():
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=exec_id, target_url="https://example.com")
    ctx.state = ExecutionState.RUNNING

    browser = MagicMock()
    browser.page = AsyncMock()
    browser.page.url = "https://example.com"
    browser.page.screenshot = AsyncMock(return_value=b"fake-jpeg")
    browser.observe = AsyncMock()

    # Request pause
    await request_pause(exec_id)

    # Cancel execution once confirmed in PAUSED
    async def cancel_when_paused():
        for _ in range(100):
            rec = await get_control_record(exec_id)
            if rec.state == ControlState.PAUSED:
                break
            await asyncio.sleep(0.01)
        await request_cancel(exec_id)

    cancel_task = asyncio.create_task(cancel_when_paused())

    handled = await runner._check_and_handle_pause(ctx, browser, exec_id, None)
    await cancel_task

    # Execution broke out without re-observing or resuming to RUNNING
    assert handled is True
    browser.observe.assert_not_called()

    await cleanup_control(exec_id)


@pytest.mark.asyncio
async def test_runner_resolves_checkpoint_on_resume():
    exec_id = str(uuid.uuid4())
    await cleanup_control(exec_id)

    runner = FlowRunner()
    ctx = ExecutionContext(execution_id=exec_id, target_url="https://example.com")
    ctx.state = ExecutionState.RUNNING

    browser = MagicMock()
    browser.page = AsyncMock()
    browser.page.url = "https://example.com"
    browser.page.screenshot = AsyncMock(return_value=b"fake-jpeg")
    browser.observe = AsyncMock(return_value={"title": "Unlocked"})

    # Raise checkpoint
    await raise_human_checkpoint(
        exec_id,
        checkpoint_type="captcha_required",
        description="Solve captcha",
    )

    # Resume once confirmed in PAUSED
    async def resume_when_paused():
        for _ in range(100):
            rec = await get_control_record(exec_id)
            if rec.state == ControlState.PAUSED:
                break
            await asyncio.sleep(0.01)
        await release_human_control(exec_id)

    task = asyncio.create_task(resume_when_paused())
    handled = await runner._check_and_handle_pause(ctx, browser, exec_id, None)
    await task

    assert handled is True
    rec = await get_control_record(exec_id)
    assert rec.checkpoint is None  # Checkpoint resolved!
    assert rec.state == ControlState.RUNNING

    await cleanup_control(exec_id)
