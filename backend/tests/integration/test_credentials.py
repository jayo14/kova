"""Integration tests for credential handling in ActionExecutor.

Tests credential resolution, masking in events, and security guarantees.
"""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.executor import ActionExecutor
from app.engine.browser.session import BrowserSession
from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
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
def credential_store():
    store = CredentialStore()
    store.add(Credential(id="login", email="test@kova.local", password="secret"))
    store.add(Credential(id="other", email="user@example.com", password="password123"))
    return store


@pytest.fixture
def execution_id():
    return uuid.uuid4()


# --- Credential resolution ---


@pytest.mark.asyncio
async def test_credential_resolves_password(test_server, browser_session, credential_store):
    """Credential ID resolves to password for type action."""
    await browser_session.page.set_content("""
        <html><body>
            <label for="pw">Password</label>
            <input type="password" id="pw" name="pw" />
        </body></html>
    """)

    executor = ActionExecutor(
        browser_session.page,
        credential_store=credential_store,
    )
    result = await executor.execute({
        "type": "type",
        "target": {"label": "Password"},
        "credential_id": "login",
    })

    assert result["success"] is True
    value = await browser_session.page.input_value("#pw")
    assert value == "secret"


@pytest.mark.asyncio
async def test_credential_missing_raises_error(test_server, browser_session):
    """Missing credential ID returns structured error."""
    await browser_session.navigate(test_server)
    executor = ActionExecutor(browser_session.page, credential_store=CredentialStore())

    result = await executor.execute({
        "type": "type",
        "target": {"css": "#username"},
        "credential_id": "nonexistent",
    })

    assert result["success"] is False
    assert result["error"]["type"] == "credential_error"
    assert "nonexistent" in result["error"]["message"]


# --- Password never in events ---


@pytest.mark.asyncio
async def test_password_not_in_event_payloads(
    test_server, browser_session, credential_store, execution_id
):
    """Password is never included in event payloads."""
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    await browser_session.page.set_content("""
        <html><body>
            <label for="pw">Password</label>
            <input type="password" id="pw" name="pw" />
        </body></html>
    """)

    executor = ActionExecutor(
        browser_session.page,
        event_recorder=recorder,
        credential_store=credential_store,
    )
    await executor.execute({
        "type": "type",
        "target": {"label": "Password"},
        "credential_id": "login",
    }, execution_id=execution_id)

    # Check all event payloads
    for event in events:
        payload_str = str(event["payload"])
        assert "secret" not in payload_str, (
            f"Password leaked in {event['type']} event: {payload_str}"
        )


@pytest.mark.asyncio
async def test_password_not_in_error_messages(
    test_server, browser_session, execution_id
):
    """Password is never included in error messages."""
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    await browser_session.navigate(test_server)
    executor = ActionExecutor(
        browser_session.page,
        event_recorder=recorder,
    )

    # Type action with a value that looks like a password
    result = await executor.execute({
        "type": "type",
        "target": {"test_id": "nonexistent"},
        "value": "mysecretpassword123",
    }, execution_id=execution_id)

    assert result["success"] is False
    # Error message should not contain the password
    assert "mysecretpassword123" not in result["error"]["message"]


# --- Full login flow with credentials ---


@pytest.mark.asyncio
async def test_login_flow_with_credential_id(
    test_server, browser_session, credential_store
):
    """Complete login flow using credential_id for password."""
    executor = ActionExecutor(
        browser_session.page,
        credential_store=credential_store,
    )

    # Navigate
    r = await executor.execute({"type": "navigate", "value": f"{test_server}/login"})
    assert r["success"]

    # Type email (direct value)
    r = await executor.execute({
        "type": "type",
        "target": {"css": "#email"},
        "value": "test@kova.local",
    })
    assert r["success"]

    # Type password (via credential)
    r = await executor.execute({
        "type": "type",
        "target": {"css": "#password"},
        "credential_id": "login",
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


# --- Credential store in ExecutionContext ---


@pytest.mark.asyncio
async def test_execution_context_holds_credentials(credential_store):
    """ExecutionContext can hold a CredentialStore."""
    from app.engine.execution.context import ExecutionContext
    from app.engine.execution.state import ExecutionState

    ctx = ExecutionContext(
        execution_id="test-123",
        target_url="http://example.com",
        credentials=credential_store,
    )

    cred = ctx.credentials.get("login")
    assert cred.get_password() == "secret"


# --- Edge cases ---


@pytest.mark.asyncio
async def test_credential_with_empty_password(test_server, browser_session):
    """Credential with empty password still works."""
    store = CredentialStore()
    store.add(Credential(id="empty", email="a@b.com", password=""))

    await browser_session.page.set_content("""
        <html><body>
            <input data-testid="field" type="text" />
        </body></html>
    """)

    executor = ActionExecutor(browser_session.page, credential_store=store)
    result = await executor.execute({
        "type": "type",
        "target": {"test_id": "field"},
        "credential_id": "empty",
    })

    assert result["success"] is True
    value = await browser_session.page.input_value("[data-testid='field']")
    assert value == ""


@pytest.mark.asyncio
async def test_credential_store_shared_between_executors(
    test_server, browser_session, credential_store
):
    """Multiple executors can share the same credential store."""
    await browser_session.page.set_content("""
        <html><body>
            <input data-testid="f1" type="text" />
            <input data-testid="f2" type="text" />
        </body></html>
    """)

    executor1 = ActionExecutor(browser_session.page, credential_store=credential_store)
    executor2 = ActionExecutor(browser_session.page, credential_store=credential_store)

    r1 = await executor1.execute({
        "type": "type",
        "target": {"test_id": "f1"},
        "credential_id": "login",
    })
    r2 = await executor2.execute({
        "type": "type",
        "target": {"test_id": "f2"},
        "credential_id": "other",
    })

    assert r1["success"] and r2["success"]
    v1 = await browser_session.page.input_value("[data-testid='f1']")
    v2 = await browser_session.page.input_value("[data-testid='f2']")
    assert v1 == "secret"
    assert v2 == "password123"
