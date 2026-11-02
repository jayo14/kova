import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.engine.browser.session import BrowserSession


def test_browser_session_in_flight_tracking():
    session = BrowserSession()
    req1 = MagicMock(url="https://api.example.com/v1/users", resource_type="fetch", method="GET")
    req2 = MagicMock(url="https://fonts.googleapis.com/css2", resource_type="font", method="GET")
    req3 = MagicMock(url="https://app.example.com/analytics/ping", resource_type="ping", method="POST")

    session.in_flight_requests[req1] = {
        "url": req1.url,
        "host": "api.example.com",
        "resource_type": "fetch",
        "method": "GET",
        "start_time": time.perf_counter() - 12.0,
    }
    session.in_flight_requests[req2] = {
        "url": req2.url,
        "host": "fonts.googleapis.com",
        "resource_type": "font",
        "method": "GET",
        "start_time": time.perf_counter() - 5.0,
    }
    session.in_flight_requests[req3] = {
        "url": req3.url,
        "host": "app.example.com",
        "resource_type": "ping",
        "method": "POST",
        "start_time": time.perf_counter() - 15.0,
    }

    pending = session.get_pending_requests()
    assert len(pending) == 3
    assert pending[0]["url"] == req3.url  # oldest first

    slowest = session.get_slowest_pending_host()
    assert slowest is not None
    # req3 is ping (ignored), req2 is font (ignored for API wait), so req1 is selected!
    assert slowest[0] == "api.example.com"
    assert slowest[1] >= 11.5


@pytest.mark.asyncio
async def test_browser_session_navigate_phases(monkeypatch):
    monkeypatch.setattr("app.engine.browser.session._is_safe_url", lambda url: True)
    session = BrowserSession()
    mock_page = AsyncMock()
    mock_resp = MagicMock(status=200)
    mock_page.goto = AsyncMock(return_value=mock_resp)
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=1200.0)
    mock_page.url = "https://app.example.com/dashboard"
    session._page = mock_page

    emitted_phases = []
    session.on_load_phase = lambda p: emitted_phases.append(p["phase"])

    phases = await session.navigate("https://app.example.com/dashboard")
    assert "commit" in phases
    assert phases["commit"]["status"] == 200
    assert "domcontentloaded" in phases
    assert "first_contentful_paint" in phases
    assert "dom_settled" in phases
    assert emitted_phases == ["commit", "domcontentloaded", "first_contentful_paint", "dom_settled"]


@pytest.mark.asyncio
async def test_browser_session_screenshot_animations_disabled():
    session = BrowserSession()
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"fake-png-bytes")
    session._page = mock_page

    res = await session.screenshot(full_page=False)
    assert res == b"fake-png-bytes"
    mock_page.screenshot.assert_called_with(full_page=False, animations="disabled")


@pytest.mark.asyncio
async def test_resource_blocking_exploration_vs_execution():
    """Amendment 5: Block only fonts, media, and analytics during exploration; never images, CSS, or JS.
    During execution/verification runs, block nothing.
    """
    # 1. Exploration session (block_heavy_resources=True)
    exp_session = BrowserSession(block_heavy_resources=True)
    assert exp_session.block_heavy_resources is True

    # 2. Execution session (block_heavy_resources=False)
    exec_session = BrowserSession(block_heavy_resources=False)
    assert exec_session.block_heavy_resources is False
