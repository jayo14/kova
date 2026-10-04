import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.infrastructure.database.session import get_session
from app.modules.auth.token_service import create_api_token, verify_api_token
from app.modules.users.models import User
from app.modules.projects.models import Project
from app.modules.flows.models import Flow
from app.modules.executions.models import Execution, ExecutionStatus
from app.api.routes.executions import _generate_report_signature, _verify_report_signature


@pytest.mark.asyncio
async def test_api_token_generation_and_verification(db_session):
    user = User(id=uuid.uuid4(), email="ci-tester@kova.local")
    db_session.add(user)
    await db_session.commit()

    token_obj, raw_token = await create_api_token(db_session, user.id, name="CI Token")
    assert raw_token.startswith("kova_tok_")

    verified = await verify_api_token(db_session, raw_token)
    assert verified is not None
    assert verified.user_id == user.id
    assert verified.last_used_at is not None

    # Invalid token check
    invalid = await verify_api_token(db_session, "kova_tok_invalid")
    assert invalid is None


@pytest.mark.asyncio
async def test_ci_run_endpoint(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="ci-user@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="CI Token")
        await db_session.commit()

        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="CI Test Project",
            base_url="https://example.com",
        )
        db_session.add(project)
        await db_session.commit()

        flow = Flow(
            id=uuid.uuid4(),
            project_id=project.id,
            name="CI Test Flow",
            steps=[{"type": "navigate", "target": {"url": "https://example.com"}}],
        )
        db_session.add(flow)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/ci/run",
                json={
                    "project_id": str(project.id),
                    "flow_ids": [str(flow.id)],
                    "base_url": "https://staging.example.com",
                },
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert response.status_code == 201
            data = response.json()
            assert data["project_id"] == str(project.id)
            assert data["count"] == 1
            assert len(data["executions"]) == 1
            assert data["executions"][0]["flow_id"] == str(flow.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_execution_report_json_and_html(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="report-user@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="Report Token")
        await db_session.commit()

        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Report Project",
            base_url="https://example.com",
        )
        db_session.add(project)
        await db_session.commit()

        flow = Flow(
            id=uuid.uuid4(),
            project_id=project.id,
            name="Report Flow",
            steps=[],
        )
        db_session.add(flow)
        await db_session.commit()

        execution = Execution(
            id=uuid.uuid4(),
            flow_id=flow.id,
            status=ExecutionStatus.COMPLETED.value,
        )
        db_session.add(execution)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Fetch JSON report via API token
            resp = await client.get(
                f"/api/v1/executions/{execution.id}/report",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["execution_id"] == str(execution.id)
            assert data["status"] == "COMPLETED"
            assert "shareable_url" in data
            assert "html" in data
            assert "signature" in data

            sig = data["signature"]
            assert _verify_report_signature(execution.id, sig)

            # 2. Access signed HTML page publicly without token
            public_resp = await client.get(
                f"/api/v1/executions/{execution.id}/report?signature={sig}&format=html"
            )
            assert public_resp.status_code == 200
            assert "text/html" in public_resp.headers["content-type"]
            assert "Kova Execution Report" in public_resp.text
            assert "Report Flow" in public_resp.text

            # 3. Invalid signature rejected
            bad_resp = await client.get(
                f"/api/v1/executions/{execution.id}/report?signature=invalid_sig"
            )
            assert bad_resp.status_code == 401
    finally:
        app.dependency_overrides.clear()
