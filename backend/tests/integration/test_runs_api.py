"""Integration tests for the Run Orchestration API (/api/v1/runs)."""

import uuid
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import get_current_user, get_session
from app.infrastructure.database.base import Base
from app.main import app
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.validation.models import ValidationRun


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
        email="orchestrator@kova.test",
        name="Orchestrator User",
    )
    db_session.add(test_user)
    await db_session.flush()

    async def override_get_session():
        yield db_session

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.test_user = test_user
        yield c

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_and_get_run(client, db_session):
    # 1. Setup project, flows, and executions
    project = Project(
        id=uuid.uuid4(),
        user_id=client.test_user.id,
        name="Quiza Test Project",
        base_url="https://quiza-ai.vercel.app",
    )
    db_session.add(project)

    flow_1 = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Interactive Quiz Flow",
        steps=[{"type": "navigate", "url": "https://quiza-ai.vercel.app"}],
    )
    flow_2 = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Study Help Flow",
        steps=[{"type": "navigate", "url": "https://quiza-ai.vercel.app"}],
    )
    db_session.add_all([flow_1, flow_2])

    exec_1 = Execution(
        id=uuid.uuid4(),
        flow_id=flow_1.id,
        status=ExecutionStatus.CREATED.value,
        flow_snapshot={"name": "Interactive Quiz Flow"},
    )
    exec_2 = Execution(
        id=uuid.uuid4(),
        flow_id=flow_2.id,
        status=ExecutionStatus.CREATED.value,
        flow_snapshot={"name": "Study Help Flow"},
    )
    db_session.add_all([exec_1, exec_2])
    await db_session.commit()

    # Mock dispatch to prevent real network calls
    with patch("app.api.dispatch.dispatch_execution") as mock_dispatch:
        mock_dispatch.return_value = None

        payload = {
            "project_id": str(project.id),
            "execution_ids": [str(exec_1.id), str(exec_2.id)],
            "concurrency_limit": 2,
            "parallel": True,
        }

        resp = await client.post("/api/v1/runs", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "RUNNING"
        assert len(data["execution_ids"]) == 2
        run_id = data["id"]

        # 2. Get Run Details
        get_resp = await client.get(f"/api/v1/runs/{run_id}")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["id"] == run_id
        assert get_data["project_id"] == str(project.id)
        assert get_data["summary"]["total"] == 2
        assert len(get_data["executions"]) == 2
        mission_names = {ex["mission_name"] for ex in get_data["executions"]}
        assert "Interactive Quiz Flow" in mission_names
        assert "Study Help Flow" in mission_names


@pytest.mark.asyncio
async def test_cancel_run(client, db_session):
    project = Project(
        id=uuid.uuid4(),
        user_id=client.test_user.id,
        name="Cancel Test Project",
        base_url="https://quiza-ai.vercel.app",
    )
    db_session.add(project)

    flow = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Cancellable Flow",
        steps=[],
    )
    db_session.add(flow)

    exec_item = Execution(
        id=uuid.uuid4(),
        flow_id=flow.id,
        status=ExecutionStatus.RUNNING.value,
    )
    db_session.add(exec_item)

    run = ValidationRun(
        id=uuid.uuid4(),
        project_id=project.id,
        base_url=project.base_url,
        status="RUNNING",
        execution_ids=[str(exec_item.id)],
        selected_flow_ids=[str(flow.id)],
        summary={"total": 1, "running": 1},
    )
    db_session.add(run)
    await db_session.commit()

    resp = await client.post(f"/api/v1/runs/{run.id}/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "CANCELLED"
