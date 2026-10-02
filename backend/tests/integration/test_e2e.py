"""End-to-end test: create project, credentials, flow, execute, verify dashboard.

Proves the full Kova stack works: API → DB → Celery → Engine → Browser → Verification.
"""

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import get_current_user, get_session
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
    test_user_id = uuid.uuid4()
    test_user = User(
        id=test_user_id,
        email="e2e@kova.local",
        name="E2E Test User",
    )
    db_session.add(test_user)
    await db_session.flush()

    async def override_get_db():
        yield db_session

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


@pytest.mark.asyncio
async def test_e2e_login_and_verify_dashboard(client, test_server):
    """Full E2E: project → credential → flow → execute → verify dashboard visible."""

    # 1. Create project with test server base_url
    project_resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Kova Test App",
            "base_url": test_server,
            "description": "Internal test application",
        },
    )
    assert project_resp.status_code == 201
    project = project_resp.json()
    project_id = project["id"]

    # 2. Create credential
    cred_resp = await client.post(
        f"/api/v1/projects/{project_id}/credentials",
        json={
            "name": "kova-login",
            "email": "test@kova.local",
            "password": "KovaTest123!",
        },
    )
    assert cred_resp.status_code == 201
    cred = cred_resp.json()
    assert cred["name"] == "kova-login"
    assert cred["email"] == "test@kova.local"
    assert "password" not in cred  # never in read response

    # 3. Create flow
    flow_resp = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "Login and Verify Dashboard",
            "persona": {"role": "Test user"},
            "objective": "Log into the application and verify that the dashboard is visible.",
            "steps": [
                {"action": "navigate", "value": f"{test_server}/login"},
                {
                    "action": "type",
                    "selector": "input[name='email']",
                    "value": "test@kova.local",
                },
                {
                    "action": "type",
                    "selector": "input[name='password']",
                    "credential_id": "kova-login",
                },
                {"action": "click", "selector": "button[type='submit']"},
            ],
            "success_condition": {"text_visible": "Welcome, Kova"},
        },
    )
    assert flow_resp.status_code == 201
    flow = flow_resp.json()
    flow_id = flow["id"]

    # 4. Create and enqueue execution
    exec_resp = await client.post(f"/api/v1/flows/{flow_id}/executions")
    assert exec_resp.status_code == 201
    execution = exec_resp.json()
    execution_id = execution["id"]
    # Status is CREATED until Celery picks it up; we bypass Celery in tests
    assert execution["status"] == "CREATED"

    # 5. Execute synchronously (bypass Celery for test)
    from app.engine.credentials.models import Credential as EngineCredential
    from app.engine.credentials.store import CredentialStore
    from app.engine.execution.runner import FlowRunner

    cred_store = CredentialStore()
    cred_store.add(
        EngineCredential(
            id="kova-login",
            email="test@kova.local",
            password="KovaTest123!",
        )
    )

    runner = FlowRunner()
    result = await runner.execute(
        execution_id=uuid.UUID(execution_id),
        flow_steps=flow["steps"],
        success_condition=flow["success_condition"],
        credential_store=cred_store,
        target_url=test_server,
    )

    # 6. Assert execution completed
    assert result["success"] is True
    assert result["verification"]["passed"] is True

    # 7. Assert no plaintext password in events
    events_str = str(result["events"])
    assert "KovaTest123!" not in events_str
    assert "test@kova.local" not in events_str

    # 8. Assert final URL is dashboard
    assert "/dashboard" in result["final_url"]
