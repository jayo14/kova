"""API integration tests.

Tests all API endpoints with proper HTTP status codes,
foreign key validation, and Pydantic schema validation.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import get_current_user, get_session
from app.infrastructure.database.base import Base
from app.main import app
from app.modules.users.models import User


@pytest.fixture
async def db_engine():
    """Create a fresh in-memory SQLite database for each test."""
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
    """Create a fresh database session."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(db_session):
    """Create an async test client with database dependency override."""

    async def override_get_session():
        yield db_session

    test_user_id = uuid.uuid4()
    test_user = User(
        id=test_user_id,
        email="api_test@example.com",
        name="API Test User",
    )
    db_session.add(test_user)
    await db_session.flush()

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def project_id(client):
    """Create a test project and return its ID."""
    response = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Test Project",
            "description": "A test project",
            "base_url": "http://localhost:3001",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.fixture
async def flow_id(client, project_id):
    """Create a test flow and return its ID."""
    response = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "Test Flow",
            "description": "A test flow",
            "steps": [
                {"action": "navigate", "selector": None, "value": "http://localhost:3001"},
                {"action": "click", "selector": "#login-btn", "value": None},
            ],
            "success_condition": {"text_visible": "Login successful"},
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


# --- Projects ---


@pytest.mark.asyncio
async def test_create_project(client):
    """POST /projects creates a project."""
    response = await client.post(
        "/api/v1/projects/",
        json={
            "name": "My Project",
            "description": "Project description",
            "base_url": "http://example.com",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Project"
    assert data["base_url"] == "http://example.com"
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_project_missing_name(client):
    """POST /projects with missing name returns 422."""
    response = await client.post(
        "/api/v1/projects/",
        json={"base_url": "http://example.com"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_project_missing_base_url(client):
    """POST /projects with missing base_url returns 422."""
    response = await client.post(
        "/api/v1/projects/",
        json={"name": "My Project"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_projects(client, project_id):
    """GET /projects returns list of projects."""
    response = await client.get("/api/v1/projects/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_project(client, project_id):
    """GET /projects/{project_id} returns project."""
    response = await client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project_id
    assert data["name"] == "Test Project"


@pytest.mark.asyncio
async def test_get_project_not_found(client):
    """GET /projects/{project_id} with invalid ID returns 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/projects/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_project_invalid_uuid(client):
    """GET /projects/{project_id} with invalid UUID returns 422."""
    response = await client.get("/api/v1/projects/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_project(client, project_id):
    """PUT /projects/{project_id} updates project."""
    response = await client.put(
        f"/api/v1/projects/{project_id}",
        json={"name": "Updated Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_project(client, project_id):
    """DELETE /projects/{project_id} deletes project."""
    response = await client.delete(f"/api/v1/projects/{project_id}")
    assert response.status_code == 204

    # Verify deleted
    response = await client.get(f"/api/v1/projects/{project_id}")
    assert response.status_code == 404


# --- Flows ---


@pytest.mark.asyncio
async def test_create_flow(client, project_id):
    """POST /flows creates a flow."""
    response = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": project_id,
            "name": "Login Flow",
            "steps": [
                {"action": "navigate", "value": "http://localhost:3001"},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Login Flow"
    assert data["project_id"] == project_id


@pytest.mark.asyncio
async def test_create_flow_invalid_project(client):
    """POST /flows with non-existent project returns 422 or 404."""
    fake_project_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/flows/",
        json={
            "project_id": fake_project_id,
            "name": "Test Flow",
            "steps": [],
        },
    )
    # FK constraint violation
    assert response.status_code in (422, 404, 500)


@pytest.mark.asyncio
async def test_list_flows(client, project_id, flow_id):
    """GET /flows returns list of flows for a project."""
    response = await client.get(f"/api/v1/flows/?project_id={project_id}")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_flow(client, flow_id):
    """GET /flows/{flow_id} returns flow."""
    response = await client.get(f"/api/v1/flows/{flow_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == flow_id
    assert data["name"] == "Test Flow"


@pytest.mark.asyncio
async def test_get_flow_not_found(client):
    """GET /flows/{flow_id} with invalid ID returns 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/flows/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_flow(client, flow_id):
    """PUT /flows/{flow_id} updates flow."""
    response = await client.put(
        f"/api/v1/flows/{flow_id}",
        json={"name": "Updated Flow"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Flow"


@pytest.mark.asyncio
async def test_delete_flow(client, flow_id):
    """DELETE /flows/{flow_id} deletes flow."""
    response = await client.delete(f"/api/v1/flows/{flow_id}")
    assert response.status_code == 204

    # Verify deleted
    response = await client.get(f"/api/v1/flows/{flow_id}")
    assert response.status_code == 404


# --- Executions ---


@pytest.mark.asyncio
async def test_create_execution(client, flow_id):
    """POST /executions creates an execution."""
    response = await client.post(
        "/api/v1/executions/",
        json={"flow_id": flow_id},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["flow_id"] == flow_id
    assert data["status"] == "CREATED"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_execution_invalid_flow(client):
    """POST /executions with non-existent flow returns error."""
    fake_flow_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/executions/",
        json={"flow_id": fake_flow_id},
    )
    # FK constraint violation
    assert response.status_code in (422, 404, 500)


@pytest.mark.asyncio
async def test_get_execution(client, flow_id):
    """GET /executions/{execution_id} returns execution."""
    # Create execution first
    create_response = await client.post(
        "/api/v1/executions/",
        json={"flow_id": flow_id},
    )
    assert create_response.status_code == 201
    execution_id = create_response.json()["id"]

    # Get execution
    response = await client.get(f"/api/v1/executions/{execution_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == execution_id
    assert data["status"] == "CREATED"


@pytest.mark.asyncio
async def test_get_execution_not_found(client):
    """GET /executions/{execution_id} with invalid ID returns 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/executions/{fake_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_executions(client, flow_id):
    """GET /executions returns list of executions."""
    response = await client.get(f"/api/v1/executions/?flow_id={flow_id}")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_cancel_execution(client, flow_id):
    """POST /executions/{execution_id}/cancel cancels execution."""
    # Create execution
    create_response = await client.post(
        "/api/v1/executions/",
        json={"flow_id": flow_id},
    )
    assert create_response.status_code == 201
    execution_id = create_response.json()["id"]

    # Cancel execution
    response = await client.post(f"/api/v1/executions/{execution_id}/cancel")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CANCELLED"
    assert data["message"] == "Execution cancelled"


@pytest.mark.asyncio
async def test_cancel_execution_not_found(client):
    """POST /executions/{execution_id}/cancel with invalid ID returns 404."""
    fake_id = str(uuid.uuid4())
    response = await client.post(f"/api/v1/executions/{fake_id}/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_execution_events(client, flow_id):
    """GET /executions/{execution_id}/events returns events."""
    # Create execution
    create_response = await client.post(
        "/api/v1/executions/",
        json={"flow_id": flow_id},
    )
    assert create_response.status_code == 201
    execution_id = create_response.json()["id"]

    # Get events
    response = await client.get(f"/api/v1/executions/{execution_id}/events")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Should have at least one event (execution.created)
    assert len(data) >= 1
    assert data[0]["event_type"] == "execution.created"


@pytest.mark.asyncio
async def test_get_execution_events_not_found(client):
    """GET /executions/{execution_id}/events with invalid ID returns 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/v1/executions/{fake_id}/events")
    assert response.status_code == 404


# --- Health ---


@pytest.mark.asyncio
async def test_health(client):
    """GET /health returns status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "environment" in data


# --- Schema validation ---


@pytest.mark.asyncio
async def test_create_project_empty_name(client):
    """POST /projects with empty name returns 422."""
    response = await client.post(
        "/api/v1/projects/",
        json={"name": "", "base_url": "http://example.com"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_flow_empty_name(client, project_id):
    """POST /flows with empty name returns 422."""
    response = await client.post(
        "/api/v1/flows/",
        json={"project_id": project_id, "name": "", "steps": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_execution_missing_flow_id(client):
    """POST /executions with missing flow_id returns 422."""
    response = await client.post(
        "/api/v1/executions/",
        json={},
    )
    assert response.status_code == 422
