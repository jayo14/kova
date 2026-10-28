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
    # Mock task enqueueing so this API test doesn't start a real browser worker.
    from app.modules.exploration.service import ExplorationService
    async def mock_execute(*args, **kwargs):
        pass
    monkeypatch.setattr(ExplorationService, "_enqueue_exploration", mock_execute)

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


@pytest.mark.asyncio
async def test_exploration_list_and_use_existing_credentials(client, db_session, monkeypatch):
    from app.modules.exploration.service import ExplorationService
    from app.modules.projects.repository import ProjectRepository
    from app.modules.credentials.service import CredentialService
    from app.modules.credentials.schemas import CredentialCreate
    from app.modules.users.models import User
    from sqlalchemy import select

    user = (await db_session.execute(select(User))).scalar_one()

    # 1. Create a project and add a stored credential to it
    proj_repo = ProjectRepository(db_session)
    project = await proj_repo.create(
        user_id=user.id,
        name="Test Platform",
        base_url="https://app.testplatform.io",
        description="Test project",
    )

    cred_service = CredentialService(db_session)
    stored_cred = await cred_service.create_credential(
        project_id=project.id,
        data=CredentialCreate(
            name="Existing Stored Account",
            email="existing-user@testplatform.io",
            password="StoredSecretPassword123!",
        ),
    )
    await db_session.commit()

    # Mock exploration task enqueueing.
    executed_creds = {}

    async def mock_enqueue(self, session_id, credential=None, **kwargs):
        executed_creds["credential"] = credential

    monkeypatch.setattr(ExplorationService, "_enqueue_exploration", mock_enqueue)

    # 2. Start an exploration session for the same domain
    start_res = await client.post(
        "/api/v1/exploration/",
        json={"url": "https://app.testplatform.io/login"},
    )
    assert start_res.status_code == 201
    session_id = start_res.json()["id"]

    # 3. Test GET /api/v1/exploration/{session_id}/credentials
    creds_res = await client.get(f"/api/v1/exploration/{session_id}/credentials")
    assert creds_res.status_code == 200
    creds_list = creds_res.json()
    assert len(creds_list) == 1
    assert creds_list[0]["id"] == str(stored_cred.id)
    assert creds_list[0]["email"] == "existing-user@testplatform.io"
    assert creds_list[0]["name"] == "Existing Stored Account"
    assert "password" not in creds_list[0]  # passwords never returned in read responses

    # 4. Submit credentials using credential_id directly (without manual email/password input)
    submit_res = await client.post(
        f"/api/v1/exploration/{session_id}/credentials",
        json={"credential_id": str(stored_cred.id)},
    )
    assert submit_res.status_code == 200
    assert submit_res.json()["status"] == "AUTHENTICATING"

    # Verify that the background flow received the decrypted credentials
    assert executed_creds.get("credential") is not None
    assert executed_creds["credential"]["email"] == "existing-user@testplatform.io"
    assert executed_creds["credential"]["password"] == "StoredSecretPassword123!"


@pytest.mark.asyncio
async def test_promote_mission_endpoint(client, db_session):
    from app.modules.projects.models import Project
    from app.modules.exploration.repository import ExplorationRepository
    from app.modules.exploration.models import ExplorationStatus
    from app.modules.users.models import User
    from sqlalchemy import select

    # Find the current test user
    stmt = select(User).where(User.email == "explorer@kova.test")
    res = await db_session.execute(stmt)
    user = res.scalar_one()

    # Create a project for this user
    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Target Project",
        base_url="https://app.target.io",
    )
    db_session.add(project)
    await db_session.flush()

    # Create an exploration session with candidate missions
    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=user.id,
        url="https://app.target.io",
        goal="explore site",
        project_id=project.id,
    )
    candidate_missions = [
        {
            "id": "mission-alpha-1",
            "title": "User Profile Edit",
            "description": "Edit display name in profile",
            "category": "feature",
            "steps": [
                {"action": "navigate", "url": "https://app.target.io/profile"},
                {"action": "fill", "target": "input#name", "value": "New Name"},
            ],
            "successCondition": {"element_visible": {"selector": ".toast-success"}},
            "confidence": 0.9,
        }
    ]
    await repo.update_status(session.id, status=ExplorationStatus.READY, candidate_missions=candidate_missions)
    await db_session.commit()

    # 1. Test successful promotion
    res = await client.post(
        f"/api/v1/exploration/{session.id}/missions/mission-alpha-1/promote",
        json={"activate_immediately": True},
    )
    assert res.status_code == 201, res.text
    flow_data = res.json()
    assert flow_data["name"] == "User Profile Edit"
    assert flow_data["project_id"] == str(project.id)
    assert flow_data["source"] == "user_provided"
    assert flow_data["active"] is True
    assert flow_data["capability"] == "feature"
    assert flow_data["success_condition"] == {"element_visible": {"selector": ".toast-success"}}

    # 2. Verify candidate_missions updated with promoted=True and flow_id
    updated_session = await repo.get_by_id(session.id)
    m = updated_session.candidate_missions[0]
    assert m["promoted"] is True
    assert m["flow_id"] == flow_data["id"]

    # 3. Test 404 for nonexistent mission
    bad_res = await client.post(
        f"/api/v1/exploration/{session.id}/missions/mission-nonexistent/promote",
        json={},
    )
    assert bad_res.status_code == 404


@pytest.mark.asyncio
async def test_exploration_project_resolution_with_extended_fields(client, db_session, monkeypatch):
    from app.modules.exploration.service import ExplorationService
    from app.modules.projects.repository import ProjectRepository

    async def mock_execute(*args, **kwargs):
        pass
    monkeypatch.setattr(ExplorationService, "_enqueue_exploration", mock_execute)

    from app.modules.users.models import User
    from sqlalchemy import select
    res = await db_session.execute(select(User).limit(1))
    test_user = res.scalar_one()

    # Pre-create a project with extended fields
    proj_repo = ProjectRepository(db_session)
    existing_proj = await proj_repo.create(
        user_id=test_user.id,
        name="Resolved App",
        base_url="https://resolved.example.com",
        product_goal="Verify signin flow",
        env_config={"target": "staging"},
    )
    await db_session.flush()

    # 1. Exploration on matching host uses existing project
    res1 = await client.post(
        "/api/v1/exploration/",
        json={"url": "https://resolved.example.com/dashboard", "goal": "check dashboard"},
    )
    assert res1.status_code == 201, res1.text
    data1 = res1.json()
    assert data1["project_id"] == str(existing_proj.id)

    # 2. Exploration on new host auto-creates project with extended fields
    res2 = await client.post(
        "/api/v1/exploration/",
        json={"url": "https://newapp.example.com/welcome", "goal": "check welcome"},
    )
    assert res2.status_code == 201, res2.text
    data2 = res2.json()
    assert data2["project_id"] is not None
    assert data2["project_id"] != str(existing_proj.id)

    new_proj = await proj_repo.get_by_id(uuid.UUID(data2["project_id"]))
    assert new_proj is not None
    assert new_proj.base_url == "https://newapp.example.com"
    assert isinstance(new_proj.env_config, dict)


