import uuid
import pytest
from sqlalchemy import select
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.flows.models import Flow
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest.fixture
async def seeded_project(db_session):
    user = User(id=uuid.uuid4(), email="explorer_test@example.com")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="LMS App",
        base_url="http://127.0.0.1:8000",
    )
    db_session.add(project)
    await db_session.flush()

    repo = ProductGraphRepository(db_session)

    # Pages
    login_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/login",
        requires_auth=False,
    )
    courses_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses",
        requires_auth=True,
    )
    enroll_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses/enroll",
        requires_auth=True,
    )

    # Actions
    await repo.create_action(
        project_id=project.id,
        page_id=courses_page.id,
        name="Browse Courses",
        action_type="click",
        selector="a[href='/courses']",
        expected_effect=[{"key": "courses_browsed", "value": True}],
    )
    await repo.create_action(
        project_id=project.id,
        page_id=enroll_page.id,
        name="Enroll Course",
        action_type="click",
        selector="button:has-text('Enroll')",
        expected_effect=[{"key": "enrolled", "value": True}],
    )
    await repo.create_action(
        project_id=project.id,
        page_id=login_page.id,
        name="Submit Login",
        action_type="click",
        selector="button[type='submit']",
        expected_effect=[{"key": "authenticated", "value": True}],
    )

    # Capabilities
    await repo.create_capability(
        project_id=project.id,
        name="authentication",
        description="User authentication and login",
        kind="auth",
        produces_state=[{"key": "authenticated", "value": True}],
    )
    await repo.create_capability(
        project_id=project.id,
        name="course_browsing",
        description="Browse available catalog of courses",
        kind="feature",
        produces_state=[{"key": "courses_browsed", "value": True}],
    )
    await repo.create_capability(
        project_id=project.id,
        name="course_enrollment",
        description="Enroll into courses",
        kind="feature",
        produces_state=[{"key": "enrolled", "value": True}],
    )

    return project


@pytest.mark.asyncio
async def test_goal_with_multiple_features_produces_multiple_flows(db_session, seeded_project):
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://127.0.0.1:8000",
        goal="sign up, log in, browse courses, enroll in a course",
        project_id=seeded_project.id,
        db_session=db_session,
    )

    missions = await explorer._build_goal_mission(
        goal="sign up, log in, browse courses, enroll in a course",
        base_url="http://127.0.0.1:8000",
        title="LMS App",
        persona="Student",
        elements=[],
        project_id=seeded_project.id,
    )

    # Must produce multiple feature missions, NOT one collapsed mega-mission
    assert len(missions) >= 2
    for m in missions:
        assert m.category == "feature"
        assert m.confidence >= 0.85
        assert m.recommended is True


@pytest.mark.asyncio
async def test_goal_with_no_matching_capabilities_falls_back_to_route_walk(db_session):
    # Empty project without capabilities
    user = User(id=uuid.uuid4(), email="empty_proj@example.com")
    db_session.add(user)
    await db_session.flush()

    empty_project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Empty App",
        base_url="http://127.0.0.1:9000",
    )
    db_session.add(empty_project)
    await db_session.flush()

    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://127.0.0.1:9000",
        goal="complete unknown workflow",
        project_id=empty_project.id,
        db_session=db_session,
    )

    missions = await explorer._build_goal_mission(
        goal="complete unknown workflow",
        base_url="http://127.0.0.1:9000",
        title="Empty App",
        persona="User",
        elements=[],
        project_id=empty_project.id,
    )

    assert len(missions) == 1
    m = missions[0]
    assert m.category == "route_walk"
    assert m.confidence == 0.3
    assert m.recommended is False
    assert "No matching capabilities found" in (m.route_analysis or {}).get("warning", "")


@pytest.mark.asyncio
async def test_generated_flows_are_persisted_with_goal_link(db_session, seeded_project):
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://127.0.0.1:8000",
        goal="browse courses, enroll in a course",
        project_id=seeded_project.id,
        db_session=db_session,
    )

    missions = await explorer._build_goal_mission(
        goal="browse courses, enroll in a course",
        base_url="http://127.0.0.1:8000",
        title="LMS App",
        persona="Student",
        elements=[],
        project_id=seeded_project.id,
    )
    assert len(missions) >= 1

    # Assert flows table has rows linked to the created goal
    stmt = select(Flow).where(Flow.project_id == seeded_project.id)
    result = await db_session.execute(stmt)
    persisted_flows = list(result.scalars().all())

    assert len(persisted_flows) >= 1
    for flow in persisted_flows:
        assert flow.goal_id is not None
        assert flow.source == "deterministic"
        assert flow.active is False


@pytest.mark.asyncio
async def test_feature_mission_skips_routes_without_capability(db_session):
    # Project with ONLY authentication capability
    user = User(id=uuid.uuid4(), email="auth_only@example.com")
    db_session.add(user)
    await db_session.flush()

    proj = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Auth Only App",
        base_url="http://127.0.0.1:8000",
    )
    db_session.add(proj)
    await db_session.flush()

    repo = ProductGraphRepository(db_session)
    await repo.create_capability(
        project_id=proj.id,
        name="authentication",
        description="Login",
        kind="auth",
        produces_state=[{"key": "authenticated", "value": True}],
    )

    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://127.0.0.1:8000",
        project_id=proj.id,
        db_session=db_session,
    )

    all_caps = await repo.list_capabilities_by_project(proj.id)

    login_route = {"path": "/login", "text": "Login", "url": "http://127.0.0.1:8000/login"}
    courses_route = {"path": "/courses", "text": "Courses", "url": "http://127.0.0.1:8000/courses"}
    dashboard_route = {"path": "/dashboard", "text": "Dashboard", "url": "http://127.0.0.1:8000/dashboard"}

    login_mission = explorer._build_feature_mission(
        login_route, "http://127.0.0.1:8000", "App", "User", all_capabilities=all_caps
    )
    courses_mission = explorer._build_feature_mission(
        courses_route, "http://127.0.0.1:8000", "App", "User", all_capabilities=all_caps
    )
    dashboard_mission = explorer._build_feature_mission(
        dashboard_route, "http://127.0.0.1:8000", "App", "User", all_capabilities=all_caps
    )

    assert login_mission is not None
    assert courses_mission is None  # Skipped!
    assert dashboard_mission is None  # Skipped!
