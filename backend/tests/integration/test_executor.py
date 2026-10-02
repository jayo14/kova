"""Integration tests for ActionExecutor.

Tests action execution against a live test server with Playwright.
Covers all action types, validation errors, target resolution, and events.
"""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.actions import ActionType, ActionValidationError
from app.engine.browser.executor import ActionExecutor
from app.engine.browser.session import BrowserSession
from tests.test_app import app as test_app


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    port = _get_free_port()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def test_server():
    async with _run_test_server() as url:
        yield url


@pytest.fixture
async def browser_session():
    async with BrowserSession() as session:
        yield session


@pytest.fixture
def execution_id():
    return uuid.uuid4()


# --- Navigate ---


@pytest.mark.asyncio
async def test_execute_navigate(test_server, browser_session):
    """Navigate action loads a URL."""
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "navigate",
        "value": f"{test_server}/login",
    })

    assert result["success"] is True
    assert result["result"]["url"].rstrip("/").endswith("/login")
    assert result["result"]["title"] == "Login"


@pytest.mark.asyncio
async def test_execute_navigate_bad_url(test_server, browser_session):
    """Navigate with invalid URL fails."""
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "navigate",
        "value": "not-a-url",
    })

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"


# --- Click ---


@pytest.mark.asyncio
async def test_execute_click_by_css(test_server, browser_session):
    """Click by CSS selector (id)."""
    await browser_session.navigate(f"{test_server}/login")
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "click",
        "target": {"css": "#login-btn"},
    })

    assert result["success"] is True
    assert result["result"]["clicked"] is True


@pytest.mark.asyncio
async def test_execute_click_by_role_name(test_server, browser_session):
    """Click by role and name."""
    await browser_session.navigate(f"{test_server}/login")
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "click",
        "target": {"role": "button", "name": "Sign in"},
    })

    assert result["success"] is True


@pytest.mark.asyncio
async def test_execute_click_by_css(test_server, browser_session):
    """Click by CSS selector."""
    await browser_session.page.set_content("""
        <html><body>
            <div id="output">unchanged</div>
            <button id="btn">Click</button>
            <script>
            document.getElementById('btn').addEventListener('click', () => {
                document.getElementById('output').textContent = 'clicked';
            });
            </script>
        </body></html>
    """)
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "click",
        "target": {"css": "#btn"},
    })

    assert result["success"] is True
    text = await browser_session.page.inner_text("#output")
    assert text == "clicked"


# --- Type ---


@pytest.mark.asyncio
async def test_execute_type_by_label(test_server, browser_session):
    """Type into input by label."""
    await browser_session.page.set_content("""
        <html><body>
            <label for="email">Email</label>
            <input type="email" id="email" name="email" />
        </body></html>
    """)
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "type",
        "target": {"label": "Email"},
        "value": "test@example.com",
    })

    assert result["success"] is True
    value = await browser_session.page.input_value("#email")
    assert value == "test@example.com"


@pytest.mark.asyncio
async def test_execute_type_by_test_id(test_server, browser_session):
    """Type into input by test ID."""
    await browser_session.page.set_content("""
        <html><body>
            <input data-testid="search" type="text" />
        </body></html>
    """)
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "type",
        "target": {"test_id": "search"},
        "value": "query",
    })

    assert result["success"] is True
    value = await browser_session.page.input_value("[data-testid='search']")
    assert value == "query"


# --- Clear ---


@pytest.mark.asyncio
async def test_execute_clear(test_server, browser_session):
    """Clear action empties an input."""
    await browser_session.page.set_content("""
        <html><body>
            <input data-testid="field" type="text" value="old content" />
        </body></html>
    """)
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "clear",
        "target": {"test_id": "field"},
    })

    assert result["success"] is True
    value = await browser_session.page.input_value("[data-testid='field']")
    assert value == ""


# --- Press ---


@pytest.mark.asyncio
async def test_execute_press(test_server, browser_session):
    """Press action sends a key."""
    await browser_session.page.set_content("""
        <html><body>
            <input data-testid="input" type="text" />
            <div id="output"></div>
            <script>
            document.querySelector('[data-testid="input"]').addEventListener('keydown', (e) => {
                document.getElementById('output').textContent = e.key;
            });
            </script>
        </body></html>
    """)
    executor = ActionExecutor(browser_session.page)
    await browser_session.page.click("[data-testid='input']")
    result = await executor.execute({"type": "press", "key": "Tab"})

    assert result["success"] is True
    assert result["result"]["pressed"] == "Tab"


# --- Scroll ---


@pytest.mark.asyncio
async def test_execute_scroll(test_server, browser_session):
    """Scroll action moves the page."""
    await browser_session.page.set_content("""
        <html><body style="height: 3000px">
            <div style="height: 100px; margin-top: 2000px" id="target">Below fold</div>
        </body></html>
    """)
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "scroll",
        "direction": "down",
        "amount": 500,
    })

    assert result["success"] is True
    assert result["result"]["scrolled"] == "down"


# --- Validation errors ---


@pytest.mark.asyncio
async def test_execute_missing_type(test_server, browser_session):
    """Missing action type returns validation error."""
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({})

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"
    assert "missing required field 'type'" in result["error"]["message"]


@pytest.mark.asyncio
async def test_execute_invalid_type(test_server, browser_session):
    """Invalid action type returns validation error."""
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({"type": "fly"})

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"


@pytest.mark.asyncio
async def test_execute_click_no_target(test_server, browser_session):
    """Click without target returns validation error."""
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({"type": "click"})

    assert result["success"] is False
    assert result["error"]["type"] == "validation_error"
    assert "requires a target" in result["error"]["message"]


# --- Target not found ---


@pytest.mark.asyncio
async def test_execute_target_not_found(test_server, browser_session):
    """Target not found returns structured error."""
    await browser_session.navigate(f"{test_server}/login")
    executor = ActionExecutor(browser_session.page)
    result = await executor.execute({
        "type": "click",
        "target": {"test_id": "nonexistent"},
    })

    assert result["success"] is False
    assert result["error"]["type"] == "target_not_found"
    assert "nonexistent" in result["error"]["message"]


# --- Event recording ---


@pytest.mark.asyncio
async def test_execute_emits_events(test_server, browser_session, execution_id):
    """Executor emits started/completed events."""
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    await browser_session.navigate(f"{test_server}/login")
    executor = ActionExecutor(browser_session.page, event_recorder=recorder)
    await executor.execute({
        "type": "click",
        "target": {"css": "#login-btn"},
    }, execution_id=execution_id)

    event_types = [e["type"] for e in events]
    assert "action.started" in event_types
    assert "action.completed" in event_types


@pytest.mark.asyncio
async def test_execute_emits_failure_event(test_server, browser_session, execution_id):
    """Executor emits action.failed on target not found."""
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    await browser_session.navigate(f"{test_server}/login")
    executor = ActionExecutor(browser_session.page, event_recorder=recorder)
    await executor.execute({
        "type": "click",
        "target": {"test_id": "no-such-element"},
    }, execution_id=execution_id)

    event_types = [e["type"] for e in events]
    assert "action.started" in event_types
    assert "action.failed" in event_types


# --- Full login flow ---


@pytest.mark.asyncio
async def test_full_login_flow(test_server, browser_session):
    """Execute a complete login flow using structured actions."""
    executor = ActionExecutor(browser_session.page)

    # Navigate
    r = await executor.execute({"type": "navigate", "value": f"{test_server}/login"})
    assert r["success"]

    # Type email
    r = await executor.execute({
        "type": "type",
        "target": {"css": "#email"},
        "value": "test@kova.local",
    })
    assert r["success"]

    # Type password
    r = await executor.execute({
        "type": "type",
        "target": {"css": "#password"},
        "value": "KovaTest123!",
    })
    assert r["success"]

    # Click login
    r = await executor.execute({
        "type": "click",
        "target": {"css": "#login-btn"},
    })
    assert r["success"]

    # Verify dashboard text
    text = await browser_session.page.inner_text("body")
    assert "Welcome, Kova" in text


# --- BrowserSession.execute_action ---


@pytest.mark.asyncio
async def test_browser_session_execute_action(test_server, browser_session):
    """BrowserSession.execute_action delegates to ActionExecutor."""
    await browser_session.navigate(f"{test_server}/login")
    result = await browser_session.execute_action({
        "type": "click",
        "target": {"css": "#login-btn"},
    })

    assert result["success"] is True
