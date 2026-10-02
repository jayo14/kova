"""Performance sanity checks.

Verifies that:
- API request → DB insert → Celery enqueue is fast (no browser in HTTP path)
- Browser execution is fully async and decoupled from API
- Each phase can be measured separately

NOT premature optimization — just sanity checks.
"""

import asyncio
import socket
import time
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import get_current_user, get_session
from app.engine.browser.session import BrowserSession
from app.engine.execution.runner import FlowRunner
from app.infrastructure.database.base import Base
from app.main import app
from app.modules.users.models import User
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

    test_user = User(
        id=uuid.uuid4(),
        email="perf_test@example.com",
        name="Perf Test User",
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


@pytest.fixture
async def test_server():
    async with _run_test_server() as url:
        yield url


# --- API request timing ---


@pytest.mark.asyncio
async def test_api_create_project_fast(client):
    """API request to create project completes in <500ms."""
    start = time.monotonic()
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Perf Test", "base_url": "http://localhost"},
    )
    elapsed = time.monotonic() - start

    assert resp.status_code == 201
    assert elapsed < 0.5, f"Project creation took {elapsed:.2f}s, expected <0.5s"


@pytest.mark.asyncio
async def test_api_create_execution_fast(client):
    """API request to create execution completes in <500ms."""
    # Create project + flow first
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Perf Test", "base_url": "http://localhost"},
    )
    project_id = proj.json()["id"]

    flow = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "Test Flow",
            "steps": [{"action": "navigate", "value": "http://localhost"}],
        },
    )
    flow_id = flow.json()["id"]

    start = time.monotonic()
    resp = await client.post(f"/api/v1/flows/{flow_id}/executions")
    elapsed = time.monotonic() - start

    assert resp.status_code == 201
    assert elapsed < 0.5, f"Execution creation took {elapsed:.2f}s, expected <0.5s"
    # Should be CREATED (not RUNNING) — Celery picks it up async
    assert resp.json()["status"] == "CREATED"


@pytest.mark.asyncio
async def test_api_list_executions_fast(client):
    """API request to list executions completes in <200ms."""
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Perf Test", "base_url": "http://localhost"},
    )
    project_id = proj.json()["id"]
    flow = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "Test Flow",
            "steps": [],
        },
    )
    flow_id = flow.json()["id"]

    # Create a few executions
    for _ in range(5):
        await client.post(f"/api/v1/flows/{flow_id}/executions")

    start = time.monotonic()
    resp = await client.get(f"/api/v1/executions/?flow_id={flow_id}")
    elapsed = time.monotonic() - start

    assert resp.status_code == 200
    assert elapsed < 0.2, f"List executions took {elapsed:.2f}s, expected <0.2s"


# --- Browser execution timing ---


@pytest.mark.asyncio
async def test_browser_startup_time(test_server):
    """Browser startup completes in <5s."""
    start = time.monotonic()
    session = BrowserSession()
    await session.start()
    startup_time = time.monotonic() - start
    await session.close()

    assert startup_time < 5.0, f"Browser startup took {startup_time:.2f}s, expected <5s"


@pytest.mark.asyncio
async def test_page_load_time(test_server):
    """Page load completes in <2s."""
    from app.engine.browser.session import BrowserSession

    async with BrowserSession() as session:
        start = time.monotonic()
        await session.navigate(f"{test_server}/login")
        load_time = time.monotonic() - start

        assert load_time < 2.0, f"Page load took {load_time:.2f}s, expected <2s"


@pytest.mark.asyncio
async def test_full_execution_time(test_server):
    """Full execution with login completes in <15s."""
    from app.engine.credentials.models import Credential
    from app.engine.credentials.store import CredentialStore

    store = CredentialStore()
    store.add(Credential(id="login", email="test@kova.local", password="KovaTest123!"))

    start = time.monotonic()
    runner = FlowRunner()
    result = await runner.execute(
        execution_id=uuid.uuid4(),
        flow_steps=[
            {"type": "navigate", "value": f"{test_server}/login"},
            {"type": "type", "target": {"css": "#email"}, "value": "test@kova.local"},
            {"type": "type", "target": {"css": "#password"}, "credential_id": "login"},
            {"type": "click", "target": {"css": "#login-btn"}},
        ],
        success_condition={"text_visible": "Welcome, Kova"},
        credential_store=store,
        target_url=test_server,
    )
    elapsed = time.monotonic() - start

    assert result["success"] is True
    assert elapsed < 15.0, f"Full execution took {elapsed:.2f}s, expected <15s"


# --- Async decoupling check ---


@pytest.mark.asyncio
async def test_execution_does_not_block_api(client, test_server):
    """Creating execution via API does NOT wait for browser execution."""
    # Create project + flow
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Perf Test", "base_url": test_server},
    )
    project_id = proj.json()["id"]
    flow = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "Login Flow",
            "steps": [
                {"action": "navigate", "value": f"{test_server}/login"},
                {"action": "type", "selector": "input[name='email']", "value": "test@kova.local"},
                {"action": "type", "selector": "input[name='password']", "value": "KovaTest123!"},
                {"action": "click", "selector": "button[type='submit']"},
            ],
            "success_condition": {"text_visible": "Welcome, Kova"},
        },
    )
    flow_id = flow.json()["id"]

    # Time the API call — should return quickly (CREATED status)
    start = time.monotonic()
    resp = await client.post(f"/api/v1/flows/{flow_id}/executions")
    elapsed = time.monotonic() - start

    assert resp.status_code == 201
    assert resp.json()["status"] == "CREATED"
    # API should return in <1s regardless of browser execution time
    assert elapsed < 1.0, f"API call took {elapsed:.2f}s — browser may be blocking"
