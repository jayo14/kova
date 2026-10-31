"""Live viewport masking acceptance tests.

Acceptance: a test proving frames of a masked field never contain the raw value.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.engine.browser.masking import (
    SENSITIVE_MASK_SELECTOR,
    build_sensitive_mask_selector,
    capture_masked_live_frame,
    validate_sensitive_selector,
)

SECRET = "SuperSecretOTP4821"


def _fake_page(masked_jpeg: bytes = b"MASKED_JPEG_CLEAN"):
    """Fake Playwright page: capture WITH mask -> clean bytes; WITHOUT mask ->
    bytes that would leak the raw password/OTP value if ever published."""

    async def screenshot(*args, **kwargs):
        if kwargs.get("mask"):
            return masked_jpeg
        return b"LEAK_" + SECRET.encode()

    page = MagicMock()
    page.is_closed = lambda: False
    page.screenshot = AsyncMock(side_effect=screenshot)
    page.locator = MagicMock(return_value=MagicMock())
    return page


@pytest.mark.asyncio
async def test_masked_field_live_frame_never_contains_raw_value():
    """Acceptance: frames of a masked field never contain the raw value."""
    page = _fake_page()
    status, frame = await capture_masked_live_frame(page)

    assert status == "masked"
    assert SECRET.encode() not in frame
    # Capture was made WITH the sensitive-field mask passed to Playwright.
    _, kwargs = page.screenshot.call_args
    assert kwargs.get("mask"), "mask must be passed on every live frame capture"
    assert "password" in str(page.locator.call_args[0][0])
    assert "otp" in str(page.locator.call_args[0][0]).lower()


@pytest.mark.asyncio
async def test_mask_failure_withholds_frame():
    """If the masked capture fails, NO unmasked frame is produced (withheld)."""
    page = _fake_page()
    page.screenshot = AsyncMock(side_effect=RuntimeError("renderer crashed"))

    status, frame = await capture_masked_live_frame(page)

    assert status == "blocked"
    assert frame == b""


@pytest.mark.asyncio
async def test_frame_producer_never_publishes_unmasked_frames():
    """The runner's frame producer publishes masking=markdown...never raw leak bytes,
    and withholds frames entirely while masking is unavailable."""
    from app.engine.execution.runner import FlowRunner
    from app.engine.execution.stream import _memory_frame_subscribers

    exec_id = "mask-runner-1"
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    _memory_frame_subscribers[exec_id] = {queue}
    try:
        # Phase 1: masking works -> the published frame is masked and clean.
        browser = MagicMock()
        browser.page = _fake_page()
        with patch(
            "app.engine.execution.runner.get_control_state",
            new=AsyncMock(return_value="agent"),
        ):
            runner = FlowRunner()
            task = asyncio.create_task(runner._frame_producer(browser, exec_id, interval=0.01))
            try:
                published = await asyncio.wait_for(queue.get(), timeout=2.0)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        frame_bytes, _state, masking = published
        assert masking == "masked"
        assert SECRET.encode() not in frame_bytes

        # Phase 2: masking unavailable -> NO frame published for a raw leak.
        browser2 = MagicMock()
        browser2.page = _fake_page_without_mask()
        _memory_frame_subscribers[exec_id] = {queue}
        with patch(
            "app.engine.execution.runner.get_control_state",
            new=AsyncMock(return_value="agent"),
        ):
            runner2 = FlowRunner()
            task2 = asyncio.create_task(runner2._frame_producer(browser2, exec_id, interval=0.01))
            await asyncio.sleep(0.08)
            task2.cancel()
            try:
                await task2
            except asyncio.CancelledError:
                pass
        # Every queued publication is masked; the producer withholds failures.
        while not queue.empty():
            published = queue.get_nowait()
            assert published[2] == "masked"
            assert SECRET.encode() not in published[0]
    finally:
        _memory_frame_subscribers.pop(exec_id, None)


def _fake_page_without_mask(masked_jpeg: bytes = b"MASKED_JPEG_CLEAN"):
    """Fake page whose masked capture works but raw fallback would leak."""

    async def screenshot(*args, **kwargs):
        if kwargs.get("mask"):
            return masked_jpeg
        return b"LEAK_" + SECRET.encode()

    page = MagicMock()
    page.is_closed = lambda: False
    page.screenshot = AsyncMock(side_effect=screenshot)
    page.locator = MagicMock(return_value=MagicMock())
    return page


@pytest.mark.asyncio
async def test_runner_withholds_frames_when_masking_fails():
    """When masked capture fails, the producer publishes NO frame and sends a
    masking=off state message (viewers told masking is off honestly)."""
    from app.engine.execution.runner import FlowRunner
    from app.engine.execution.stream import _memory_frame_subscribers, _memory_state_subscribers

    exec_id = "mask-runner-2"
    frame_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    state_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    _memory_frame_subscribers[exec_id] = {frame_queue}
    _memory_state_subscribers[exec_id] = {state_queue}
    try:
        broken = MagicMock()
        broken.is_closed = lambda: False
        broken.screenshot = AsyncMock(side_effect=RuntimeError("masking unavailable"))
        browser = MagicMock()
        browser.page = broken
        with patch(
            "app.engine.execution.runner.get_control_state",
            new=AsyncMock(return_value="agent"),
        ):
            runner = FlowRunner()
            task = asyncio.create_task(runner._frame_producer(browser, exec_id, interval=0.01))
            try:
                state_msg = await asyncio.wait_for(state_queue.get(), timeout=2.0)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        assert state_msg.get("masking") == "off"
        assert frame_queue.empty()
    finally:
        _memory_frame_subscribers.pop(exec_id, None)
        _memory_state_subscribers.pop(exec_id, None)


def test_extra_configured_sensitive_selectors_are_masked(monkeypatch):
    """Configured sensitive selectors extend the shared mask selector."""
    monkeypatch.setattr(
        settings,
        "LIVE_FRAME_EXTRA_SENSITIVE_SELECTORS",
        "#billing-api-key, input[name='cvv']",
        raising=False,
    )
    selector = build_sensitive_mask_selector(
        [s.strip() for s in settings.LIVE_FRAME_EXTRA_SENSITIVE_SELECTORS.split(",") if s.strip()]
    )
    assert SENSITIVE_MASK_SELECTOR in selector
    assert "#billing-api-key" in selector
    assert "input[name='cvv']" in selector


def test_invalid_extra_selectors_are_rejected():
    """Unsafe selectors from configuration never reach the browser."""
    assert validate_sensitive_selector("input[name='cvv']") is True
    assert validate_sensitive_selector("") is False
    assert validate_sensitive_selector("input; drop table") is False
    assert validate_sensitive_selector("input{x:1}") is False
    assert validate_sensitive_selector("x" * 300) is False
    selector = build_sensitive_mask_selector(["evil;input", "input[name='otp2']"])
    assert "evil;input" not in selector
    assert "input[name='otp2']" in selector
