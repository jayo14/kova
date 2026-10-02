"""Browser integration tests for the unified BrowserSession abstraction.

These tests verify that the BrowserSession works correctly with Playwright
Chromium, including navigation, actions, observation, and cleanup.
"""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.session import BrowserSession
from tests.test_app import app as test_app


def _get_free_port() -> int:
    """Get a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    """Start the test FastAPI app on a free port."""
    port = _get_free_port()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait for server to be ready
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def test_server():
    """Fixture that provides a running test server URL."""
    async with _run_test_server() as url:
        yield url


@pytest.mark.asyncio
async def test_browser_session_starts_and_closes(test_server):
    """Browser session starts and closes cleanly."""
    browser = BrowserSession()
    assert not browser.is_started

    await browser.start()
    assert browser.is_started
    assert browser.page is not None

    await browser.close()
    assert not browser.is_started


@pytest.mark.asyncio
async def test_browser_session_context_manager(test_server):
    """Browser session works as async context manager."""
    async with BrowserSession() as browser:
        assert browser.is_started
        assert browser.page is not None
    assert not browser.is_started


@pytest.mark.asyncio
async def test_navigate(test_server):
    """Navigate to a URL and verify page loads."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        assert browser.page.url == f"{test_server}/"
        title = await browser.page.title()
        assert title == "Kova Test App"


@pytest.mark.asyncio
async def test_observe_page(test_server):
    """Observe page and get interactive elements."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        observation = await browser.observe()

        assert observation["title"] == "Kova Test App"
        assert observation["url"] == f"{test_server}/"
        assert len(observation["elements"]) >= 3  # username, password, login-btn

        selectors = [el["selector"] for el in observation["elements"]]
        assert "#username" in selectors
        assert "#password" in selectors
        assert "#login-btn" in selectors


@pytest.mark.asyncio
async def test_click(test_server):
    """Click an element on the page."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        # Click the login button (should show login behavior)
        await browser.click("#login-btn")
        # No error means click succeeded


@pytest.mark.asyncio
async def test_type_and_fill(test_server):
    """Type text into an input field."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        await browser.type("#username", "admin")
        await browser.type("#password", "secret")

        # Verify the values were entered
        username_value = await browser.page.input_value("#username")
        password_value = await browser.page.input_value("#password")
        assert username_value == "admin"
        assert password_value == "secret"


@pytest.mark.asyncio
async def test_clear(test_server):
    """Clear an input field."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        await browser.type("#username", "admin")
        assert await browser.page.input_value("#username") == "admin"

        await browser.clear("#username")
        assert await browser.page.input_value("#username") == ""


@pytest.mark.asyncio
async def test_press_key(test_server):
    """Press a keyboard key."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        await browser.type("#username", "admin")
        await browser.press("Tab")
        # Tab moved focus to next element (password), no error


@pytest.mark.asyncio
async def test_scroll(test_server):
    """Scroll the page."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        # Should not raise
        await browser.scroll("down", 200)
        await browser.scroll("up", 100)


@pytest.mark.asyncio
async def test_screenshot(test_server):
    """Take a screenshot."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)
        screenshot = await browser.screenshot()
        assert isinstance(screenshot, bytes)
        assert len(screenshot) > 0
        # PNG screenshots start with the PNG magic bytes
        assert screenshot[:4] == b"\x89PNG"


@pytest.mark.asyncio
async def test_full_login_flow(test_server):
    """Complete login flow: fill form, submit, verify result."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)

        # Fill the login form
        await browser.type("#username", "admin")
        await browser.type("#password", "secret")

        # Submit by clicking the login button
        await browser.click("#login-btn")

        # Wait for result div to appear
        await browser.page.wait_for_selector("#result", state="visible", timeout=3000)

        # Verify the welcome message changed
        welcome_text = await browser.page.inner_text("#welcome")
        assert welcome_text == "Hello, admin!"

        # Verify result is visible
        result_text = await browser.page.inner_text("#result")
        assert result_text == "Login successful!"


@pytest.mark.asyncio
async def test_failed_login_shows_no_result(test_server):
    """Failed login doesn't show the result div."""
    async with BrowserSession() as browser:
        await browser.navigate(test_server)

        await browser.type("#username", "wrong")
        await browser.type("#password", "wrong")
        await browser.click("#login-btn")

        # Wait a moment for any potential DOM update
        await asyncio.sleep(0.2)

        # Result should still be hidden
        result = await browser.page.query_selector("#result")
        assert result is not None
        is_visible = await result.is_visible()
        assert not is_visible


@pytest.mark.asyncio
async def test_isolation_between_sessions(test_server):
    """Two browser sessions are isolated from each other."""
    async with BrowserSession() as browser1:
        await browser1.navigate(test_server)
        await browser1.type("#username", "user1")

        async with BrowserSession() as browser2:
            await browser2.navigate(test_server)
            await browser2.type("#username", "user2")

            # Each session has its own state
            val1 = await browser1.page.input_value("#username")
            val2 = await browser2.page.input_value("#username")
            assert val1 == "user1"
            assert val2 == "user2"


@pytest.mark.asyncio
async def test_close_is_idempotent(test_server):
    """Closing a session multiple times doesn't raise."""
    browser = BrowserSession()
    await browser.start()
    await browser.close()
    # Second close should not raise
    await browser.close()
    assert not browser.is_started


@pytest.mark.asyncio
async def test_page_property_raises_before_start():
    """Accessing page before start raises RuntimeError."""
    browser = BrowserSession()
    with pytest.raises(RuntimeError, match="not started"):
        _ = browser.page
