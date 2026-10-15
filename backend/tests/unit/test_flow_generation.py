import uuid
from unittest.mock import AsyncMock, PropertyMock, patch

from app.engine.ai.settings import AISettings

import pytest

from app.modules.flows.generator import (
    DeterministicFlowGenerator,
    ExecutionStep,
    GeneratedFlow,
    GenerationRequest,
    GenerationResult,
    diff_flows,
    step_assert,
    step_click,
    step_input,
    step_locate,
    step_navigate,
    to_gherkin_representation,
    to_json_representation,
)
from app.modules.flows.schemas import FlowStateContract, StateAssertion
from app.modules.flows.service import FlowService
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest.fixture
async def seed_product_graph(db_session):
    """Seed a rich Product Graph with pages, actions, capabilities, personas, and goals."""
    user = User(id=uuid.uuid4(), email="flow_gen@test.com")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Buggy Demo App",
        base_url="http://127.0.0.1:8000",
    )
    db_session.add(project)
    await db_session.flush()

    repo = ProductGraphRepository(db_session)

    # 1. Personas
    student = await repo.create_persona(
        project_id=project.id,
        name="Student",
        description="Standard student learner",
        credentials_required=True,
        default_capabilities=["course_browsing", "course_enrollment", "authentication"],
    )

    # 2. Pages
    login_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/login",
        title="Login Page",
        requires_auth=False,
    )
    catalog_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses",
        title="Course Catalog",
        requires_auth=False,
    )
    course_detail_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses/:id",
        title="Course Detail",
        requires_auth=True,
    )

    # 3. Actions
    email_act = await repo.create_action(
        project_id=project.id,
        page_id=login_page.id,
        name="Email Field",
        selector="#email",
        action_type="input",
    )
    pwd_act = await repo.create_action(
        project_id=project.id,
        page_id=login_page.id,
        name="Password Field",
        selector="#password",
        action_type="input",
    )
    signin_act = await repo.create_action(
        project_id=project.id,
        page_id=login_page.id,
        name="Sign In Button",
        selector="#signin-btn",
        action_type="submit",
        expected_effect=[{"key": "authenticated", "action": "set", "value": True}],
        mutates=["authenticated"],
    )

    browse_act = await repo.create_action(
        project_id=project.id,
        page_id=catalog_page.id,
        name="View Course Card",
        selector=".course-card",
        action_type="click",
        expected_effect=[{"key": "catalog_viewed", "action": "set", "value": True}],
        mutates=["catalog_viewed"],
    )

    enroll_act = await repo.create_action(
        project_id=project.id,
        page_id=course_detail_page.id,
        name="Enroll Button",
        selector="#enroll-now-btn",
        action_type="click",
        expected_effect=[{"key": "enrolled", "action": "set", "value": True}],
        mutates=["enrolled"],
    )

    # 4. Capabilities
    auth_cap = await repo.create_capability(
        project_id=project.id,
        name="authentication",
        description="User sign-in capability",
        produces_state=[{"key": "authenticated", "action": "set", "value": True}],
        kind="primary",
    )
    browse_cap = await repo.create_capability(
        project_id=project.id,
        name="course_browsing",
        description="Course browsing capability",
        produces_state=[{"key": "catalog_viewed", "action": "set", "value": True}],
        kind="primary",
    )
    enroll_cap = await repo.create_capability(
        project_id=project.id,
        name="course_enrollment",
        description="Course enrollment capability",
        requires_capabilities=["authentication"],
        requires_state=[{"key": "authenticated", "value": True}],
        produces_state=[{"key": "enrolled", "action": "set", "value": True}],
        kind="primary",
    )

    # 5. Goals
    enroll_goal = await repo.create_goal(
        project_id=project.id,
        name="Enroll in Course as Student",
        persona_id=student.id,
        success_criteria=[{"key": "enrolled", "value": True}],
        source="user_provided",
    )

    return {
        "user": user,
        "project": project,
        "student": student,
        "enroll_goal": enroll_goal,
        "login_page": login_page,
        "catalog_page": catalog_page,
        "course_detail_page": course_detail_page,
        "auth_cap": auth_cap,
        "browse_cap": browse_cap,
        "enroll_cap": enroll_cap,
    }


@pytest.mark.asyncio
async def test_deterministic_flow_generation(db_session, seed_product_graph):
    data = seed_product_graph
    generator = DeterministicFlowGenerator(db_session)

    req = GenerationRequest(
        project_id=data["project"].id,
        goal_id=data["enroll_goal"].id,
    )
    flows, unresolved = await generator.generate(req)

    assert len(unresolved) == 0
    assert len(flows) >= 1

    flow = flows[0]
    assert isinstance(flow, GeneratedFlow)
    assert flow.source == "deterministic"
    assert flow.confidence == 1.0
    assert flow.goal_id == data["enroll_goal"].id
    assert flow.persona_id == data["student"].id

    # Verify internal representation
    assert len(flow.internal) > 0
    assert all(isinstance(s, ExecutionStep) for s in flow.internal)
    step_actions = [s.action for s in flow.internal]
    assert "navigate" in step_actions
    assert "click" in step_actions
    assert "assert" in step_actions
    assert "capture_evidence" in step_actions

    # Verify JSON representation
    assert flow.json_repr is not None
    assert flow.json_repr["name"] == flow.name
    assert flow.json_repr["source"] == "deterministic"
    assert len(flow.json_repr["steps"]) == len(flow.internal)

    # Verify Gherkin representation
    assert "Feature:" in flow.gherkin
    assert "Scenario:" in flow.gherkin
    assert "Given" in flow.gherkin
    assert "When" in flow.gherkin
    assert "Then" in flow.gherkin


@pytest.mark.asyncio
async def test_unresolved_goal_with_ai_disabled(db_session, seed_product_graph):
    data = seed_product_graph
    repo = ProductGraphRepository(db_session)

    # Add goal that has no matching capability
    impossible_goal = await repo.create_goal(
        project_id=data["project"].id,
        name="Mine Bitcoin from Dashboard",
        success_criteria=[{"key": "bitcoin_mined", "value": True}],
    )

    with patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=False):
        service = FlowService(db_session)
        result = await service.generate_flows(
            project_id=data["project"].id,
            goal_id=impossible_goal.id,
        )

        assert len(result.flows) == 0
        assert "Mine Bitcoin from Dashboard" in result.unresolved_goals
        assert len(result.ai_proposals) == 0


@pytest.mark.asyncio
async def test_unresolved_goal_with_ai_enabled(db_session, seed_product_graph):
    data = seed_product_graph
    repo = ProductGraphRepository(db_session)

    impossible_goal = await repo.create_goal(
        project_id=data["project"].id,
        name="Request Refund for Course",
        success_criteria=[{"key": "refund_issued", "value": True}],
    )

    with patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True):
        service = FlowService(db_session)
        result = await service.generate_flows(
            project_id=data["project"].id,
            goal_id=impossible_goal.id,
        )

        assert len(result.flows) >= 1
        ai_flow = result.flows[0]
        assert ai_flow.source == "ai_proposal"
        assert ai_flow.confidence <= 0.9

        assert len(result.ai_proposals) >= 1
        prop = result.ai_proposals[0]
        assert prop.stage == "flow_generation"
        assert prop.confidence <= 0.9
        assert "Refund" in prop.input_summary


def test_diff_flows_representation():
    flow_a = {
        "name": "Auth Flow",
        "source": "deterministic",
        "confidence": 1.0,
        "steps": [
            {"action": "navigate", "target": "/login", "value": "/login"},
            {"action": "click", "target": "#submit", "value": None},
        ],
        "state_contract": {"requires": [], "produces": [{"key": "auth", "value": True}]},
    }
    flow_b = {
        "name": "Auth Flow",
        "source": "deterministic",
        "confidence": 1.0,
        "steps": [
            {"action": "navigate", "target": "/login", "value": "/login"},
            {"action": "input", "target": "#email", "value": "test@test.com"},
            {"action": "click", "target": "#submit", "value": None},
        ],
        "state_contract": {"requires": [], "produces": [{"key": "auth", "value": True}]},
    }

    diff = diff_flows(flow_a, flow_b)
    assert len(diff["added_steps"]) == 1 or len(diff["modified_steps"]) == 1


def test_gherkin_export_structure():
    steps = [
        step_navigate("/login"),
        step_locate("#email"),
        step_input("#email", "alice@example.com"),
        step_click("#login-btn"),
        step_assert("url_matches", "/dashboard"),
    ]
    gherkin = to_gherkin_representation("Login as Alice", steps)

    assert "Feature: Login as Alice" in gherkin
    assert "Scenario: Execute Login as Alice" in gherkin
    assert 'Given the user navigates to "/login"' in gherkin
    assert 'the user enters "alice@example.com" into "#email"' in gherkin
    assert 'the user clicks the "#login-btn" element' in gherkin
    assert 'Then the URL should match "/dashboard"' in gherkin


@pytest.mark.asyncio
async def test_buggy_demo_produces_three_core_flows(db_session, seed_product_graph):
    """Assert a full generation against the demo Product Graph produces authentication, browsing, and enrollment."""
    data = seed_product_graph
    service = FlowService(db_session)

    # 1. Generate auth flow
    res_auth = await service.generate_flows(data["project"].id, target_capability="authentication")
    # 2. Generate browsing flow
    res_browse = await service.generate_flows(data["project"].id, target_capability="course_browsing")
    # 3. Generate enrollment flow
    res_enroll = await service.generate_flows(data["project"].id, target_capability="course_enrollment")

    assert len(res_auth.flows) >= 1
    assert len(res_browse.flows) >= 1
    assert len(res_enroll.flows) >= 1

    all_generated_flows = res_auth.flows + res_browse.flows + res_enroll.flows
    assert len(all_generated_flows) >= 3

    flow_names = [f.name.lower() for f in all_generated_flows]
    assert any("auth" in n for n in flow_names)
    assert any("browsing" in n for n in flow_names)
    assert any("enrollment" in n for n in flow_names)


@pytest.mark.asyncio
async def test_flows_persisted_as_inactive(db_session, seed_product_graph):
    """Assert generated flows are saved to database with active=False, awaiting human review."""
    data = seed_product_graph
    service = FlowService(db_session)

    await service.generate_flows(data["project"].id, target_capability="authentication")

    db_flows = await service.list_flows(data["project"].id)
    assert len(db_flows) >= 1
    for flow in db_flows:
        if flow.source in ("deterministic", "ai_proposal"):
            assert flow.active is False, "Generated flows must be inactive by default until reviewed"


@pytest.mark.asyncio
async def test_generate_flows_api_endpoint_permissions(db_session, seed_product_graph):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    from app.api import get_current_user, get_session

    data = seed_product_graph
    user = data["user"]
    project = data["project"]

    other_user = User(
        id=uuid.uuid4(),
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="otherpasshash",
    )
    db_session.add(other_user)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.dependency_overrides = {}
        app.dependency_overrides[get_session] = lambda: db_session

        # 1. Project owner/admin -> 200 OK
        app.dependency_overrides[get_current_user] = lambda: user
        res = await client.post(
            f"/api/v1/projects/{project.id}/flows:generate",
            json={"target_capability": "course_browsing"},
        )
        assert res.status_code == 200
        gen_data = res.json()
        assert "flows" in gen_data
        assert len(gen_data["flows"]) >= 1

        # 2. Non-admin / non-member -> 403 Forbidden
        app.dependency_overrides[get_current_user] = lambda: other_user
        res_forbidden = await client.post(
            f"/api/v1/projects/{project.id}/flows:generate",
            json={"target_capability": "course_browsing"},
        )
        assert res_forbidden.status_code == 403

        # 3. Non-existent project -> 404
        random_id = uuid.uuid4()
        res_not_found = await client.post(
            f"/api/v1/projects/{random_id}/flows:generate",
            json={"target_capability": "course_browsing"},
        )
        assert res_not_found.status_code == 404

        app.dependency_overrides.clear()

