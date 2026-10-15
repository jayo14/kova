"""Integration test for Change Impact Analysis with Product Graph and ValidationService."""
from __future__ import annotations

import uuid
import pytest

from app.modules.flows.models import Flow
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.product_graph.service import ProductGraphService
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.validation.service import ValidationService


@pytest.mark.asyncio
async def test_impact_analysis_end_to_end_with_seeded_product_graph(db_session):
    # 1. Seed user and project
    user = User(id=uuid.uuid4(), email="impact-test@kova.local")
    db_session.add(user)
    await db_session.commit()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="LMS Impact Test Project",
        base_url="https://lms.test",
        product_graph_version=1,
    )
    db_session.add(project)
    await db_session.commit()

    repo = ProductGraphRepository(db_session)
    pg_service = ProductGraphService(db_session)

    # 2. Seed pages
    page_courses = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses",
        source_files=["src/pages/Course.tsx"],
    )
    page_enroll = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses/enroll",
        source_files=["src/pages/Enroll.tsx", "src/api/enrollment.ts"],
    )
    page_assignment = await repo.create_page(
        project_id=project.id,
        url_pattern="/assignments",
        source_files=["src/pages/Assignment.tsx"],
    )
    page_grades = await repo.create_page(
        project_id=project.id,
        url_pattern="/grades",
        source_files=["src/pages/Grades.tsx"],
    )

    # 3. Seed capabilities
    cap_auth = await repo.create_capability(
        project_id=project.id,
        name="authentication",
        kind="shared",
        source_files=["src/components/AuthProvider.tsx"],
        produces_state=[{"key": "authenticated:student"}],
    )
    cap_enroll = await repo.create_capability(
        project_id=project.id,
        name="course_enrollment",
        kind="primary",
        source_files=["src/api/enrollment.ts"],
        produces_state=[{"key": "enrolled:course_X"}],
    )
    cap_assign = await repo.create_capability(
        project_id=project.id,
        name="assignment_submission",
        kind="primary",
        source_files=["src/pages/Assignment.tsx"],
        produces_state=[{"key": "assignment:submitted"}],
    )
    cap_grade = await repo.create_capability(
        project_id=project.id,
        name="grade_viewing",
        kind="primary",
        source_files=["src/pages/Grades.tsx"],
        produces_state=[{"key": "grade:viewed"}],
    )

    # 4. Seed flows
    flow_auth = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="authenticate_as_student",
        capability="authentication",
        routes=["/login"],
        status="active",
        active=True,
        provides_capabilities=["authentication"],
        state_contract={"produces": [{"key": "authenticated:student", "value": True}]},
    )
    flow_enroll = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="enroll_in_course",
        capability="course_enrollment",
        page_ids=[str(page_courses.id), str(page_enroll.id)],
        routes=["/courses/enroll"],
        status="active",
        active=True,
        provides_capabilities=["course_enrollment"],
        dependencies=[{"kind": "capability", "value": "authentication"}],
        state_contract={
            "requires": [{"key": "authenticated:student", "value": True}],
            "produces": [{"key": "enrolled:course_X", "value": True}],
            "mutates": ["enrolled:course_X"],
        },
    )
    flow_submit = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="submit_assignment",
        capability="assignment_submission",
        page_ids=[str(page_assignment.id)],
        routes=["/assignments"],
        status="active",
        active=True,
        dependencies=[
            {"kind": "capability", "value": "authentication"},
            {"kind": "flow", "value": str(flow_enroll.id)},
        ],
        state_contract={
            "requires": [
                {"key": "authenticated:student", "value": True},
                {"key": "enrolled:course_X", "value": True},
            ],
            "produces": [{"key": "assignment:submitted", "value": True}],
        },
    )
    flow_grade = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="view_grade",
        capability="grade_viewing",
        page_ids=[str(page_grades.id)],
        routes=["/grades"],
        status="active",
        active=True,
        dependencies=[{"kind": "capability", "value": "authentication"}],
        state_contract={
            "requires": [
                {"key": "authenticated:student", "value": True},
                {"key": "assignment:submitted", "value": True},
            ],
            "produces": [{"key": "grade:viewed", "value": True}],
        },
    )
    flow_inactive = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="draft_unreviewed_flow",
        capability="course_enrollment",
        status="inactive",
        active=False,
        state_contract={},
    )
    db_session.add_all([flow_auth, flow_enroll, flow_submit, flow_grade, flow_inactive])
    await db_session.commit()

    # 5. Seed invariant
    inv = await repo.create_invariant(
        project_id=project.id,
        name="Enrolled courses appear on dashboard",
        assertion={"key": "enrolled:course_X", "predicate": "eq", "value": True},
        checked_by_flow_ids=[str(flow_enroll.id)],
    )

    # 6. Export snapshot and create ProductGraphVersion
    snapshot = await pg_service.export(project.id)
    await repo.create_version(
        project_id=project.id,
        version=1,
        change_summary="Initial integration test snapshot",
        snapshot=snapshot,
    )
    await db_session.commit()

    # 7. Simulate git diff touching enrollment API
    git_diff = """diff --git a/src/api/enrollment.ts b/src/api/enrollment.ts
--- a/src/api/enrollment.ts
+++ b/src/api/enrollment.ts
@@ -1,3 +1,3 @@
-export function enroll() {}
+export function enrollV2() {}
"""

    val_service = ValidationService(db_session)
    report = await val_service.analyze_impact(
        project_id=project.id,
        diff_content=git_diff,
    )

    assert report.product_graph_consulted is True
    assert "course_enrollment" in report.affected_capabilities

    affected_names = {f.name for f in report.affected_flows}
    assert "enroll_in_course" in affected_names
    assert "submit_assignment" in affected_names
    assert "view_grade" in affected_names
    # Prerequisite must not be in affected_flows
    assert "authenticate_as_student" not in affected_names
    # Inactive flow must not be in affected_flows
    assert "draft_unreviewed_flow" not in affected_names

    # Assert minimal execution plan sequences prerequisite first
    assert report.minimal_execution_plan is not None
    plan_names = [s.flow_name for s in report.minimal_execution_plan.steps]
    assert "authenticate_as_student" in plan_names
    assert plan_names[0] == "authenticate_as_student"
    # Ensure auth appears once
    auth_occurrences = [s for s in report.minimal_execution_plan.steps if s.flow_name == "authenticate_as_student"]
    assert len(auth_occurrences) == 1

    # Invariants
    assert len(report.affected_invariants) == 1
    assert report.affected_invariants[0].name == "Enrolled courses appear on dashboard"

    # Traversal log exists and is populated
    assert len(report.graph_traversal_log) > 0


@pytest.mark.asyncio
async def test_impact_analysis_empty_product_graph_in_db_returns_graceful_report(db_session):
    user = User(id=uuid.uuid4(), email="empty-impact@kova.local")
    db_session.add(user)
    await db_session.commit()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Empty Graph Project",
        base_url="https://empty.test",
    )
    db_session.add(project)
    await db_session.commit()

    val_service = ValidationService(db_session)
    report = await val_service.analyze_impact(
        project_id=project.id,
        changed_files=["src/pages/Home.tsx"],
    )

    assert report.product_graph_consulted is False
    assert report.confidence == 0.0
    assert report.recommended_scope == "full"
    assert report.minimal_execution_plan is None
    assert len(report.uncertainty) > 0
    assert "No Product Graph available" in report.uncertainty[0]
