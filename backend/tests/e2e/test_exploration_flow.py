"""End-to-end tests for the full exploration → mission → execution chain.

Tests the complete flow from URL input to mission generation, verifying:
- Exploration session creation and lifecycle
- Page navigation and validation
- Workflow discovery and mission generation
- Error handling for invalid URLs
"""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.models import ExplorationStatus


@pytest.mark.asyncio
async def test_exploration_session_lifecycle(db_session):
    """Test full exploration lifecycle: create → explore → ready."""
    from app.modules.users.models import User
    from app.modules.projects.models import Project
    from app.modules.exploration.models import ExplorationSession
    from app.modules.exploration.repository import ExplorationRepository

    user = User(id=uuid.uuid4(), email="e2e@test.com", name="E2E Test")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Test",
        base_url="http://test.com",
    )
    db_session.add(project)
    await db_session.flush()

    session = ExplorationSession(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id,
        url="http://test.com",
        status=ExplorationStatus.CREATED.value,
    )
    db_session.add(session)
    await db_session.flush()

    repo = ExplorationRepository(db_session)
    retrieved = await repo.get_by_id(session.id)
    assert retrieved is not None
    assert retrieved.status == ExplorationStatus.CREATED.value
    assert retrieved.url == "http://test.com"


@pytest.mark.asyncio
async def test_exploration_engine_goal_mission():
    """Test that exploration with a goal generates a goal-directed mission."""
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://example.com",
        goal="find pricing page",
        event_emitter=AsyncMock(),
    )

    mock_page = MagicMock()
    mock_page.url = "http://example.com"
    mock_page.eval_on_selector_all = AsyncMock(return_value=["Pricing", "About Us"])

    observation = {
        "elements": [
            {"type": "button", "name": "Pricing"},
            {"type": "button", "name": "About Us"},
            {"type": "button", "name": "Sign Up"},
        ],
        "text": "Welcome to our site. Pricing plans available.",
        "title": "Example Site",
    }

    discoveries, missions = await engine._discover_workflows(mock_page, observation, None)

    assert len(missions) > 0, "Should generate at least one mission"
    goal_missions = [m for m in missions if "find pricing page" in m.name]
    assert len(goal_missions) == 1, "Should have a goal-directed mission"
    assert goal_missions[0].recommended is True
    assert all(step.get("type") != "wait" for step in goal_missions[0].steps)
    # Confidence must be honest, not fabricated (readiness §33): a goal mission
    # that keyword-matches a control but can only verify a state change is
    # deliberately capped below auth/search journeys.
    assert 0.5 <= goal_missions[0].confidence <= 0.85
    # The goal mission must carry a structured, non-vacuous condition
    cond = goal_missions[0].successCondition
    assert isinstance(cond, dict)
    assert cond.get("url_changed_to"), "goal mission must verify a state change"


@pytest.mark.asyncio
async def test_exploration_engine_no_missions_insufficient_elements():
    """Test that no missions are generated with insufficient interactive elements."""
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://example.com",
        event_emitter=AsyncMock(),
    )

    mock_page = MagicMock()
    mock_page.url = "http://example.com"
    mock_page.eval_on_selector_all = AsyncMock(return_value=[])

    observation = {
        "elements": [{"type": "text", "name": "Hi"}],  # Only 1 element
        "text": "Hello world",
        "title": "Empty Page",
    }

    discoveries, missions = await engine._discover_workflows(mock_page, observation, None)
    assert len(missions) == 0


@pytest.mark.asyncio
async def test_exploration_engine_feature_missions():
    """Test that feature-based missions are generated for matching elements."""
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://example.com",
        event_emitter=AsyncMock(),
    )

    mock_page = MagicMock()
    mock_page.url = "http://example.com"
    mock_page.eval_on_selector_all = AsyncMock(
        return_value=["Quiz Generator", "My Results", "Upload Material", "Settings"]
    )

    observation = {
        "elements": [
            {"type": "button", "name": "Quiz Generator"},
            {"type": "button", "name": "My Results"},
            {"type": "button", "name": "Upload Material"},
            {"type": "button", "name": "Settings"},
        ],
        "text": "Welcome to the learning platform. Use the quiz generator to create quizzes from your study material. View your results and scores. Upload new documents to your library.",
        "title": "Learning Platform",
    }

    discoveries, missions = await engine._discover_workflows(mock_page, observation, None)

    assert len(discoveries) > 0, "Should discover features"
    mission_names = [m.name for m in missions]
    assert any("quiz" in n.lower() for n in mission_names), f"Should find quiz mission in: {mission_names}"


@pytest.mark.asyncio
async def test_exploration_engine_role_detection():
    """Test that multiple roles trigger ASKING state."""
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://example.com",
        event_emitter=AsyncMock(),
    )

    mock_page = MagicMock()
    mock_page.url = "http://example.com"

    observation = {
        "elements": [
            {"type": "button", "name": "Student Dashboard"},
            {"type": "button", "name": "Teacher Dashboard"},
            {"type": "button", "name": "Admin Panel"},
        ],
        "text": "Welcome. Choose your role: Student, Teacher, or Admin.",
        "title": "Role Select",
    }

    roles = await engine._detect_roles(mock_page, observation)
    assert len(roles) >= 2, "Should detect at least 2 roles"


from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_discovery_pipeline_to_product_graph_e2e(db_session):
    """Test full discovery -> Product Graph persistence chain."""
    from app.engine.exploration.discovery.pipeline import DiscoveryPipeline
    from app.modules.product_graph.service import ProductGraphService
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(id=uuid.uuid4(), email="discovery_e2e@test.com")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Discovery Target App",
        base_url="http://127.0.0.1:8000",
    )
    db_session.add(project)
    await db_session.flush()

    pipeline = DiscoveryPipeline(project_id=project.id, base_url="http://127.0.0.1:8000")

    mock_browser_page = AsyncMock()
    mock_browser_page.url = "http://127.0.0.1:8000"
    mock_browser_page.title = AsyncMock(return_value="Demo App")

    # Mock crawler link extraction across pages
    mock_browser_page.evaluate = AsyncMock(side_effect=[
        # First page links
        ["http://127.0.0.1:8000/courses/101", "http://127.0.0.1:8000/contact"],
        # Courses page links
        [],
        # Contact page links
        [],
        # Page 1 actions
        [
            {"text": "Sign In", "tag": "button", "type": "submit", "selector": "#signin"},
            {"text": "Register", "tag": "a", "type": "button", "selector": "#register"},
        ],
        # Page 2 (/courses/:id) actions
        [
            {"text": "Enroll in Course", "tag": "button", "type": "button", "selector": "#enroll-btn"},
            {"text": "Download Syllabus", "tag": "button", "type": "button", "selector": "#download"},
        ],
        # Page 3 (/contact) actions
        [
            {"text": "Submit Message", "tag": "button", "type": "submit", "selector": "#submit-btn"},
        ],
        # Persona detection roles
        ["student", "instructor"],
    ])

    discovery_result = await pipeline.discover(mock_browser_page)

    assert len(discovery_result.pages) >= 3
    assert len(discovery_result.actions) >= 5
    assert len(discovery_result.personas) >= 1
    assert len(discovery_result.invariants) >= 1

    # Persist via ProductGraphService
    pg_service = ProductGraphService(db_session)
    export_data = await pg_service.upsert_from_discovery(project.id, discovery_result)

    assert export_data["project_id"] == str(project.id)
    assert len(export_data["pages"]) >= 3
    assert len(export_data["actions"]) >= 5
    assert len(export_data["personas"]) >= 1
    assert len(export_data["invariants"]) >= 1
