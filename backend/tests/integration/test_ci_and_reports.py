"""Integration tests for CI continuous validation, targeted regression execution, and reports."""
from __future__ import annotations

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.infrastructure.database.session import get_session
from app.modules.auth.token_service import create_api_token
from app.modules.flows.models import Flow
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.product_graph.service import ProductGraphService
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _seed_lms_project(db_session):
    user = User(id=uuid.uuid4(), email="ci-integration@kova.local")
    db_session.add(user)
    await db_session.commit()

    token_obj, raw_token = await create_api_token(db_session, user.id, name="CI Token")
    await db_session.commit()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="LMS CI Validation Project",
        base_url="https://lms-ci.test",
        product_graph_version=1,
    )
    db_session.add(project)
    await db_session.commit()

    repo = ProductGraphRepository(db_session)
    pg_service = ProductGraphService(db_session)

    p_courses = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses",
        source_files=["src/pages/Course.tsx"],
    )
    p_enroll = await repo.create_page(
        project_id=project.id,
        url_pattern="/courses/enroll",
        source_files=["src/pages/Enroll.tsx", "src/api/enrollment.ts"],
    )

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
        page_ids=[str(p_courses.id), str(p_enroll.id)],
        routes=["/courses/enroll"],
        status="active",
        active=True,
        provides_capabilities=["course_enrollment"],
        dependencies=[{"kind": "capability", "value": "authentication"}],
        state_contract={
            "requires": [{"key": "authenticated:student", "value": True}],
            "produces": [{"key": "enrolled:course_X", "value": True}],
        },
    )
    db_session.add_all([flow_auth, flow_enroll])
    await db_session.commit()

    snapshot = await pg_service.export(project.id)
    await repo.create_version(
        project_id=project.id,
        version=1,
        change_summary="Initial CI snapshot",
        snapshot=snapshot,
    )
    await db_session.commit()

    return user, project, raw_token, flow_auth, flow_enroll


@pytest.mark.asyncio
async def test_ci_validate_diff_endpoint(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user, project, raw_token, flow_auth, flow_enroll = await _seed_lms_project(db_session)
        headers = {"Authorization": f"Bearer {raw_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/ci/validate",
                json={
                    "project_id": str(project.id),
                    "diff_content": """diff --git a/src/api/enrollment.ts b/src/api/enrollment.ts
--- a/src/api/enrollment.ts
+++ b/src/api/enrollment.ts
@@ -1,3 +1,3 @@
-export function enroll() {}
+export function enrollV2() {}
""",
                    "commit_message": "Update enrollment API",
                },
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["overall_status"] == "passed"
            assert "course_enrollment" in data["impact_report"]["affected_capabilities"]
            # Prerequisite flow authenticate_as_student is omitted because it passed
            assert len(data["results"]) == 1
            assert data["results"][0]["flow_name"] == "enroll_in_course"
            assert data["results"][0]["status"] == "passed"
            assert "started_at" in data
            assert "finished_at" in data
            assert data["duration_ms"] >= 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ci_validate_empty_graph_reports_no_graph(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user = User(id=uuid.uuid4(), email="ci-empty-graph@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="CI Token Empty")
        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Empty Graph Project",
            base_url="https://empty.test",
        )
        db_session.add(project)
        await db_session.commit()

        headers = {"Authorization": f"Bearer {raw_token}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/ci/validate",
                json={
                    "project_id": str(project.id),
                    "changed_files": ["src/pages/Enroll.tsx"],
                },
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["overall_status"] == "no_graph"
            assert data["results"] == []
            assert "No Product Graph available" in data["impact_report"]["uncertainty"][0]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ci_validate_empty_plan_reports_no_flows(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user, project, raw_token, flow_auth, flow_enroll = await _seed_lms_project(db_session)
        headers = {"Authorization": f"Bearer {raw_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/ci/validate",
                json={
                    "project_id": str(project.id),
                    "changed_files": ["docs/README.md"],
                },
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["overall_status"] == "no_flows"
            assert data["results"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ci_run_legacy_and_diff_routes(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user, project, raw_token, flow_auth, flow_enroll = await _seed_lms_project(db_session)
        headers = {"Authorization": f"Bearer {raw_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Diff route via /api/v1/ci/run
            resp_diff = await client.post(
                "/api/v1/ci/run",
                json={
                    "project_id": str(project.id),
                    "changed_files": ["src/api/enrollment.ts"],
                },
                headers=headers,
            )
            assert resp_diff.status_code == 200
            diff_data = resp_diff.json()
            assert "overall_status" in diff_data
            assert diff_data["overall_status"] == "passed"

            # 2. Legacy flow_ids route via /api/v1/ci/run
            resp_legacy = await client.post(
                "/api/v1/ci/run",
                json={
                    "project_id": str(project.id),
                    "flow_ids": [str(flow_auth.id)],
                },
                headers=headers,
            )
            assert resp_legacy.status_code == 201
            legacy_data = resp_legacy.json()
            assert legacy_data["count"] == 1
            assert len(legacy_data["executions"]) == 1

            # 3. Missing both returns 400
            resp_bad = await client.post(
                "/api/v1/ci/run",
                json={"project_id": str(project.id)},
                headers=headers,
            )
            assert resp_bad.status_code == 400
    finally:
        app.dependency_overrides.clear()
