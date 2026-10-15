import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.modules.flows.repository import FlowRepository
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.product_graph.schemas import (
    Action,
    Capability,
    DiscoveryResult,
    Goal,
    Invariant,
    Page,
    Persona,
    State,
)
from app.modules.product_graph.service import ProductGraphService
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User


@pytest.fixture
async def user_and_project(db_session):
    user = User(
        id=uuid.uuid4(),
        email=f"tester-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="testpasshash",
    )
    db_session.add(user)
    await db_session.flush()

    project_repo = ProjectRepository(db_session)
    project = await project_repo.create(
        user_id=user.id,
        name="LMS Platform",
        base_url="http://localhost:8000",
        description="Learning Management System",
    )
    return user, project


@pytest.mark.asyncio
async def test_product_graph_nine_entities_seed_and_roundtrip(db_session, user_and_project):
    _, project = user_and_project
    repo = ProductGraphRepository(db_session)
    flow_repo = FlowRepository(db_session)

    # 1. Persona
    student = await repo.create_persona(
        project_id=project.id,
        name="student",
        description="Enrolls in courses and submits assignments",
        credentials_required=True,
        default_capabilities=["view_courses"],
    )
    assert student.name == "student"

    # 2. Goal
    goal = await repo.create_goal(
        project_id=project.id,
        name="Student Course Enrollment",
        persona_id=student.id,
        success_criteria=[{"key": "enrolled", "value": True, "predicate": "eq"}],
        source="discovered",
    )
    assert goal.name == "Student Course Enrollment"

    # 3. Page
    course_page = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses/:id",
        title="Course Details",
        requires_auth=True,
        source_files=["app/views/courses.py"],
    )
    assert course_page.url_pattern == "/courses/:id"

    # 4. Action
    action = await repo.create_action(
        project_id=project.id,
        page_id=course_page.id,
        name="Click Enroll Button",
        selector="button#enroll-btn",
        action_type="click",
        expected_effect=[{"key": "enrolled", "value": True, "predicate": "eq"}],
        mutates=["enrolled"],
    )
    assert action.selector == "button#enroll-btn"

    # 5. Capability
    capability = await repo.create_capability(
        project_id=project.id,
        name="course_enrollment",
        description="Capacity to enroll student in course",
        requires_capabilities=["authentication"],
        requires_state=[{"key": "authenticated", "value": True, "predicate": "eq"}],
        produces_state=[{"key": "enrolled", "action": "set", "value": True}],
        kind="primary",
        source_files=["app/services/enrollment.py"],
    )
    assert capability.name == "course_enrollment"

    # 6. State
    state = await repo.create_state(
        project_id=project.id,
        key="enrolled",
        value_type="bool",
        default_value=False,
        description="Whether current student is enrolled in current course",
    )
    assert state.key == "enrolled"

    # 7. Flow
    flow = await flow_repo.create(
        project_id=project.id,
        name="Enroll In Biology 101",
        goal_id=goal.id,
        persona_id=student.id,
        page_ids=[str(course_page.id)],
        capability="course_enrollment",
        routes=["/courses/:id"],
        state_contract={
            "requires": [{"key": "authenticated", "value": True, "predicate": "eq"}],
            "produces": [{"key": "enrolled", "value": True, "predicate": "eq"}],
        },
    )
    assert flow.goal_id == goal.id
    assert flow.persona_id == student.id
    assert str(course_page.id) in flow.page_ids

    # 8. Dependency
    dep = await repo.create_dependency(
        project_id=project.id,
        flow_id=flow.id,
        depends_on_kind="capability",
        depends_on_id="authentication",
        required=True,
    )
    assert dep.depends_on_id == "authentication"

    # 9. Invariant
    invariant = await repo.create_invariant(
        project_id=project.id,
        name="Enrolled course appears in student dashboard",
        assertion={"key": "dashboard_enrolled_courses_contains", "value": True, "predicate": "eq"},
        checked_by_flow_ids=[str(flow.id)],
    )
    assert invariant.name == "Enrolled course appears in student dashboard"

    # Test full export via service
    service = ProductGraphService(db_session)
    export_data = await service.export(project.id)
    assert export_data["project_id"] == str(project.id)
    assert len(export_data["personas"]) == 1
    assert len(export_data["goals"]) == 1
    assert len(export_data["pages"]) == 1
    assert len(export_data["actions"]) == 1
    assert len(export_data["capabilities"]) == 1
    assert len(export_data["states"]) == 1
    assert len(export_data["flows"]) == 1
    assert len(export_data["dependencies"]) == 1
    assert len(export_data["invariants"]) == 1


@pytest.mark.asyncio
async def test_product_graph_traversal_helpers(db_session, user_and_project):
    _, project = user_and_project
    repo = ProductGraphRepository(db_session)
    flow_repo = FlowRepository(db_session)

    # Seed entities
    page = await repo.create_page(project_id=project.id, url_pattern="/dashboard")
    cap = await repo.create_capability(
        project_id=project.id,
        name="profile_update",
        produces_state=[{"key": "profile_updated", "action": "set", "value": True}],
    )
    flow = await flow_repo.create(
        project_id=project.id,
        name="Update Profile Flow",
        capability="profile_update",
        page_ids=[str(page.id)],
        routes=["/dashboard"],
        state_contract={
            "requires": [{"key": "authenticated", "value": True, "predicate": "eq"}],
            "produces": [{"key": "profile_updated", "value": True, "predicate": "eq"}],
        },
    )
    inv = await repo.create_invariant(
        project_id=project.id,
        name="Profile update persists",
        assertion={"key": "profile_updated", "value": True, "predicate": "eq"},
        checked_by_flow_ids=[str(flow.id)],
    )

    # 1. flows_producing_capability
    producing_flows = await repo.flows_producing_capability(project.id, "profile_update")
    assert len(producing_flows) == 1
    assert producing_flows[0].id == flow.id

    # 2. flows_requiring_state
    requiring_flows = await repo.flows_requiring_state(project.id, "authenticated")
    assert len(requiring_flows) == 1
    assert requiring_flows[0].id == flow.id

    # 3. pages_touched_by_flow
    touched_pages = await repo.pages_touched_by_flow(flow.id)
    assert len(touched_pages) == 1
    assert touched_pages[0].id == page.id

    # 4. capabilities_produced_by_flow
    produced_caps = await repo.capabilities_produced_by_flow(flow.id)
    assert len(produced_caps) == 1
    assert produced_caps[0].name == "profile_update"

    # 5. invariants_checked_by_flow
    checked_invs = await repo.invariants_checked_by_flow(flow.id)
    assert len(checked_invs) == 1
    assert checked_invs[0].id == inv.id


@pytest.mark.asyncio
async def test_product_graph_merge_user_edit_and_diff(db_session, user_and_project):
    _, project = user_and_project
    service = ProductGraphService(db_session)
    repo = ProductGraphRepository(db_session)

    # Initialize v1
    cap = await repo.create_capability(
        project_id=project.id,
        name="checkout",
        source_files=["app/checkout.py"],
    )
    v1_snap = await service.export(project.id)
    await repo.create_version(project.id, version=1, change_summary="v1 initial", snapshot=v1_snap)

    # User edit: update source_files on capability
    updated_cap = await service.merge_user_edit(
        project_id=project.id,
        entity_type="capability",
        entity_id=cap.id,
        patch={"source_files": ["app/checkout.py", "app/payments/stripe.py"]},
    )
    assert updated_cap.user_edited is True
    assert "app/payments/stripe.py" in updated_cap.source_files

    # Project version should have bumped to 2
    assert project.product_graph_version == 2

    # Compute diff between v1 and v2
    diff = await service.diff(from_version=1, to_version=2, project_id=project.id)
    assert diff.from_version == 1
    assert diff.to_version == 2
    assert "capabilities" in diff.changed
    assert len(diff.changed["capabilities"]) == 1


@pytest.mark.asyncio
async def test_product_graph_upsert_from_discovery_preserves_user_edits(db_session, user_and_project):
    _, project = user_and_project
    service = ProductGraphService(db_session)
    repo = ProductGraphRepository(db_session)

    # Seed capability marked as user-edited
    await repo.create_capability(
        project_id=project.id,
        name="custom_auth",
        description="Manual customized auth setup",
        source_files=["auth/custom.py"],
        user_edited=True,
    )

    # Run discovery with the same capability name but generic auto-discovered description
    disc = DiscoveryResult(
        capabilities=[
            Capability(
                project_id=project.id,
                name="custom_auth",
                description="Auto discovered basic auth",
                source_files=["auth/generic.py"],
                provider_flow_ids=["flow-disc-1"],
            )
        ]
    )

    await service.upsert_from_discovery(project.id, disc)

    # Fetch back
    stored_cap = await repo.get_capability_by_name(project.id, "custom_auth")
    assert stored_cap is not None
    # User-edited description must be preserved!
    assert stored_cap.description == "Manual customized auth setup"
    # New provider flow ID was merged
    assert "flow-disc-1" in stored_cap.provider_flow_ids


@pytest.mark.asyncio
async def test_product_graph_api_endpoints_permissions(db_session, user_and_project):
    user, project = user_and_project
    other_user = User(
        id=uuid.uuid4(),
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="otherpasshash",
    )
    db_session.add(other_user)
    await db_session.flush()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Override get_current_user to return owner
        app.dependency_overrides = {}
        from app.api import get_current_user, get_session

        app.dependency_overrides[get_session] = lambda: db_session

        # 1. Owner access -> 200
        app.dependency_overrides[get_current_user] = lambda: user
        res = await client.get(f"/api/v1/projects/{project.id}/product-graph")
        assert res.status_code == 200
        data = res.json()
        assert data["project_id"] == str(project.id)

        # 2. Non-owner access -> 403
        app.dependency_overrides[get_current_user] = lambda: other_user
        res_forbidden = await client.get(f"/api/v1/projects/{project.id}/product-graph")
        assert res_forbidden.status_code == 403

        # 3. Non-existent project -> 404
        random_id = uuid.uuid4()
        res_not_found = await client.get(f"/api/v1/projects/{random_id}/product-graph")
        assert res_not_found.status_code == 404

        # Clean up overrides
        app.dependency_overrides.clear()
