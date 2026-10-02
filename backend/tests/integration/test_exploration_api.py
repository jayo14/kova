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
        email="explorer@kova.test",
        name="Explorer User",
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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_and_get_exploration_session(client, monkeypatch):
    # Mock background exploration execution so it doesn't try to open a real browser in unit test
    from app.modules.exploration.service import ExplorationService
    async def mock_execute(*args, **kwargs):
        pass
    monkeypatch.setattr(ExplorationService, "_execute_exploration_flow", mock_execute)

    response = await client.post(
        "/api/v1/exploration/",
        json={"url": "https://tastiq.app.vercel.app", "goal": "test quiz generation"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["url"] == "https://tastiq.app.vercel.app"
    assert data["goal"] == "test quiz generation"
    assert data["status"] == "CREATED"
    session_id = data["id"]

    # Test GET
    get_res = await client.get(f"/api/v1/exploration/{session_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == session_id

    # Test Cancel
    cancel_res = await client.post(f"/api/v1/exploration/{session_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_exploration_missions_persistence_and_recovery(client, db_session):
    from app.modules.exploration.repository import ExplorationRepository
    from app.modules.exploration.models import ExplorationStatus

    repo = ExplorationRepository(db_session)
    # Create test session
    user_res = await client.get("/api/v1/exploration/nonexistent")
    # Fetch existing user from db
    from app.modules.users.models import User
    from sqlalchemy import select
    user = (await db_session.execute(select(User))).scalar_one()

    session = await repo.create(
        user_id=user.id,
        url="https://www.summastudy.com.ng",
        goal=None,
    )

    sample_discoveries = [
        {"label": "Get started", "description": "Actionable interface region"},
        {"label": "Search", "description": "Actionable interface region"},
    ]
    sample_missions = [
        {
            "id": "mission-1",
            "name": "Explore Get started",
            "title": "Explore Get started",
            "description": "Navigate to Get started",
            "steps": [{"type": "navigate", "url": "https://www.summastudy.com.ng"}, {"type": "click", "target": "button:has-text('Get started')"}],
            "recommended": True,
        }
    ]

    # Update discoveries, missions and READY status
    await repo.update_status(
        session_id=session.id,
        status=ExplorationStatus.READY,
        discoveries=sample_discoveries,
        candidate_missions=sample_missions,
    )
    await db_session.commit()

    # Verify GET /api/v1/exploration/{id} returns discoveries and candidate missions
    res = await client.get(f"/api/v1/exploration/{session.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "READY"
    assert len(body["discoveries"]) == 2
    assert body["discoveries"][0]["label"] == "Get started"
    assert len(body["candidate_missions"]) == 1
    assert body["candidate_missions"][0]["name"] == "Explore Get started"
    assert body["candidate_missions"][0]["steps"][1]["target"] == "button:has-text('Get started')"

