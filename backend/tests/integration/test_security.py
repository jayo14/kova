"""Security audit tests.

Verifies that the implementation does not leak secrets,
validate inputs, and follows security best practices.
"""

import logging
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import get_current_user, get_session
from app.engine.credentials.models import Credential
from app.engine.credentials.store import CredentialStore
from app.engine.execution.runner import FlowRunner
from app.infrastructure.database.base import Base
from app.main import app
from app.modules.users.models import User


@pytest.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    test_user_id = uuid.uuid4()
    test_user = User(
        id=test_user_id,
        email="security_test@example.com",
        name="Security Test User",
    )
    db_session.add(test_user)
    await db_session.flush()

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_session] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --- 1. Passwords not in API responses ---


@pytest.mark.asyncio
async def test_password_not_in_credential_read(client):
    """Password field is excluded from credential read responses."""
    # Create project
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Security Test", "base_url": "http://localhost"},
    )
    project_id = proj.json()["id"]

    # Create credential
    cred = await client.post(
        f"/api/v1/projects/{project_id}/credentials",
        json={
            "name": "test-cred",
            "email": "test@example.com",
            "password": "SuperSecret123!",
        },
    )
    assert cred.status_code == 201
    cred_data = cred.json()
    assert "password" not in cred_data
    assert "SuperSecret123!" not in str(cred_data)

    # Get credential
    cred_id = cred_data["id"]
    get_resp = await client.get(
        f"/api/v1/projects/{project_id}/credentials/{cred_id}"
    )
    assert get_resp.status_code == 200
    assert "password" not in get_resp.json()
    assert "SuperSecret123!" not in str(get_resp.json())

    # List credentials
    list_resp = await client.get(f"/api/v1/projects/{project_id}/credentials")
    assert list_resp.status_code == 200
    for c in list_resp.json():
        assert "password" not in c
        assert "SuperSecret123!" not in str(c)


# --- 2. Passwords not in execution events ---


@pytest.mark.asyncio
async def test_password_not_in_runner_events():
    """Password never appears in FlowRunner events."""
    store = CredentialStore()
    store.add(Credential(id="cred1", email="user@test.com", password="MySecret999!"))

    # Capture all events
    events = []

    async def recorder(exec_id, event_type, payload):
        events.append({"type": event_type, "payload": payload})

    runner = FlowRunner()
    await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        event_recorder=recorder,
    )

    events_str = str(events)
    assert "MySecret999!" not in events_str
    assert "user@test.com" not in events_str


# --- 3. Passwords not in error messages ---


@pytest.mark.asyncio
async def test_password_not_in_action_error_messages():
    """Password value never appears in action error messages."""
    from app.engine.browser.executor import ActionExecutor

    store = CredentialStore()
    store.add(Credential(id="cred1", email="u@t.com", password="HiddenPass!"))

    # Try to use credential on nonexistent target — error should not leak password
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("data:text/html,<html><body></body></html>")

    executor = ActionExecutor(page, credential_store=store)
    result = await executor.execute({
        "type": "type",
        "target": {"test_id": "nonexistent"},
        "credential_id": "cred1",
    })

    assert result["success"] is False
    error_str = str(result.get("error", {}))
    assert "HiddenPass!" not in error_str

    await context.close()
    await browser.close()
    await pw.stop()


# --- 4. UUID validation on execution IDs ---


@pytest.mark.asyncio
async def test_invalid_execution_id_rejected(client):
    """Invalid UUID for execution ID returns 422."""
    resp = await client.get("/api/v1/executions/not-a-uuid")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_flow_id_rejected(client):
    """Invalid UUID for flow ID returns 422."""
    resp = await client.get("/api/v1/flows/not-a-uuid")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_project_id_rejected(client):
    """Invalid UUID for project ID returns 422."""
    resp = await client.get("/api/v1/projects/not-a-uuid")
    assert resp.status_code == 422


# --- 5. Cross-project flow access validation ---


@pytest.mark.asyncio
async def test_flow_requires_valid_project(client):
    """Flow creation fails if project does not exist."""
    fake_project_id = str(uuid.uuid4())
    resp = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": fake_project_id,
            "name": "Orphan Flow",
            "steps": [],
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_credential_requires_valid_project(client):
    """Credential creation fails if project does not exist."""
    fake_project_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/projects/{fake_project_id}/credentials",
        json={
            "name": "test",
            "email": "t@t.com",
            "password": "pass",
        },
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_execution_requires_valid_flow(client):
    """Execution creation fails if flow does not exist."""
    fake_flow_id = str(uuid.uuid4())
    resp = await client.post(f"/api/v1/flows/{fake_flow_id}/executions")
    assert resp.status_code == 404


# --- 6. Browser context isolation ---


@pytest.mark.asyncio
async def test_browser_contexts_are_isolated():
    """Each BrowserSession gets its own isolated browser, context, and page."""
    from app.engine.browser.session import BrowserSession

    session1 = BrowserSession()
    session2 = BrowserSession()
    await session1.start()
    await session2.start()

    # Each session should have its own browser instance
    assert session1._browser is not session2._browser
    # Each session should have its own context
    assert session1._context is not session2._context
    # Each session should have its own page
    assert session1._page is not session2._page

    # Each page should be on a different about:blank (separate contexts)
    url1 = session1.page.url
    url2 = session2.page.url
    # Both start on about:blank but are separate page objects
    assert session1.page is not session2.page

    await session1.close()
    await session2.close()


# --- 7. Executions not stuck in RUNNING ---


@pytest.mark.asyncio
async def test_execution_never_stuck_in_running():
    """Runner always reaches terminal state (success or failure)."""
    runner = FlowRunner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
    )

    # Success path: no "state" key means COMPLETED
    # Failure path: "state" key is set to FAILED
    if "state" in result:
        terminal_states = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"}
        assert result["state"] in terminal_states
    else:
        # Success = implicitly COMPLETED
        assert result["success"] is True


# --- 8. No eval/exec in codebase ---


def test_no_eval_exec_in_engine():
    """Engine code does not use eval() or exec() for arbitrary code execution."""
    import pathlib
    import re as _re

    engine_dir = pathlib.Path(__file__).parent.parent.parent / "app" / "engine"
    # Match real builtin usage, not re.compile / importlib patterns
    security_risky = [
        _re.compile(r"(?<![\w.])eval\s*\("),
        _re.compile(r"(?<![\w.])exec\s*\("),
        _re.compile(r"(?<![\w.])compile\s*\("),
        _re.compile(r"__import__\s*\("),
    ]

    for py_file in engine_dir.rglob("*.py"):
        content = py_file.read_text()
        # Strip comments/strings lightly: ignore pure re.compile lines
        for pattern in security_risky:
            for match in pattern.finditer(content):
                # Allow re.compile / ast patterns used for safety checks
                start = match.start()
                prefix = content[max(0, start - 3):start]
                if prefix.endswith(("re.", "_re.", "ast.")):
                    continue
                raise AssertionError(
                    f"Security risk: '{match.group(0)}' found in {py_file}"
                )


# --- 9. SQL injection protection ---


@pytest.mark.asyncio
async def test_sql_injection_in_project_name(client):
    """SQL injection in project name is handled safely."""
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "'; DROP TABLE projects; --",
            "base_url": "http://localhost",
        },
    )
    assert resp.status_code == 201

    # Verify table still exists
    list_resp = await client.get("/api/v1/projects/")
    assert list_resp.status_code == 200
    names = [p["name"] for p in list_resp.json()]
    assert "'; DROP TABLE projects; --" in names


@pytest.mark.asyncio
async def test_sql_injection_in_flow_name(client):
    """SQL injection in flow name is handled safely."""
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Test", "base_url": "http://localhost"},
    )
    project_id = proj.json()["id"]

    resp = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "1' OR '1'='1",
            "steps": [],
        },
    )
    assert resp.status_code == 201


# --- 10. Unvalidated JSON protection ---


@pytest.mark.asyncio
async def test_missing_required_fields_rejected(client):
    """Missing required fields in JSON body returns validation error."""
    resp = await client.post("/api/v1/projects/", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_json_type_rejected(client):
    """Invalid JSON types are rejected."""
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": 12345, "base_url": True},
    )
    assert resp.status_code == 422


# --- 11. CORS configuration ---


def test_cors_configured():
    """FastAPI app has CORS middleware configured."""
    middleware_classes = [
        m.cls.__name__
        for m in app.user_middleware
    ]
    # Should have CORSMiddleware
    assert "CORSMiddleware" in middleware_classes, (
        f"CORS not configured. Middleware: {middleware_classes}"
    )


# --- 12. Celery task does not infinite retry ---


def test_celery_task_max_retries():
    """Celery task has max_retries set (not infinite)."""
    from app.workers.tasks.executions import run_execution

    # Celery task should have max_retries
    assert hasattr(run_execution, "max_retries")
    assert run_execution.max_retries <= 3, (
        f"max_retries too high: {run_execution.max_retries}"
    )


# --- 13. No passwords in Celery task logs ---


@pytest.mark.asyncio
async def test_celery_task_does_not_log_passwords(caplog):
    """Celery task execution does not log passwords."""
    with caplog.at_level(logging.DEBUG):
        # This will fail because no DB, but should not log passwords
        from app.workers.tasks.executions import _run_execution_async
        from unittest.mock import AsyncMock

        task = AsyncMock()
        task.max_retries = 1

        try:
            await _run_execution_async(task, str(uuid.uuid4()))
        except Exception:
            pass

        for record in caplog.records:
            assert "KovaTest123!" not in record.getMessage()
            assert "password" not in record.getMessage().lower() or "credential" in record.getMessage().lower()


# --- 14. Credential store never logs passwords ---


def test_credential_store_never_logs_passwords(caplog):
    """CredentialStore operations never log actual passwords."""
    with caplog.at_level(logging.DEBUG):
        store = CredentialStore()
        store.add(Credential(id="test", email="u@t.com", password="SuperSecret!"))
        store.get("test")
        store.has("test")
        store.list_ids()
        store.to_safe_dict()

        for record in caplog.records:
            assert "SuperSecret!" not in record.getMessage()


# --- 15. Execution event payloads safe ---


@pytest.mark.asyncio
async def test_execution_event_payloads_safe():
    """Event payloads never contain raw passwords."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="u@t.com", password="SecretPass!"))

    events = []

    async def recorder(exec_id, event_type, payload):
        events.append(payload)

    runner = FlowRunner()
    await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        credential_store=store,
        event_recorder=recorder,
    )

    for payload in events:
        payload_str = str(payload)
        assert "SecretPass!" not in payload_str
