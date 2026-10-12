import argparse
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock

from app.main import app
from app.infrastructure.database.session import get_session
from app.modules.auth.token_service import create_api_token
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.validation.models import ValidationRun, ValidationStatus
from scripts.kova_ci import run_ci


@pytest.mark.asyncio
async def test_ci_validate_api_flow(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="cv-tester@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="CV Token")
        await db_session.commit()

        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="CV Project",
            base_url="https://cv.test",
        )
        db_session.add(project)
        await db_session.commit()

        flow = Flow(
            id=uuid.uuid4(),
            project_id=project.id,
            name="Auth Login Flow",
            capability="authentication",
            routes=["/login"],
            criticality="critical",
            status="active",
            steps=[{"action": "navigate", "value": "https://cv.test/login"}],
        )
        db_session.add(flow)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {raw_token}"}

            # 1. Trigger validation via /api/v1/ci/validate
            resp = await client.post(
                "/api/v1/ci/validate",
                json={
                    "project_id": str(project.id),
                    "commit_sha": "a1b2c3d4",
                    "branch": "feature/login-fix",
                    "scope": "targeted",
                    "changed_files": ["app/auth/login.py"],
                },
                headers=headers,
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["project_id"] == str(project.id)
            assert data["scope"] == "targeted"
            assert data["status"] == "RUNNING"
            assert str(flow.id) in data["selected_flow_ids"]
            assert len(data["execution_ids"]) == 1
            vrun_id = data["id"]

            # 2. Poll validation status
            poll_resp = await client.get(f"/api/v1/ci/validate/{vrun_id}", headers=headers)
            assert poll_resp.status_code == 200
            poll_data = poll_resp.json()
            assert poll_data["id"] == vrun_id

            # 3. Retrieve validation report
            rep_resp = await client.get(f"/api/v1/ci/validate/{vrun_id}/report", headers=headers)
            assert rep_resp.status_code == 200
            rep_data = rep_resp.json()
            assert rep_data["validation_run_id"] == vrun_id
            assert "impact_report" in rep_data
            assert "authentication" in rep_data["impact_report"]["affected_capabilities"]

            # 4. Check project knowledge endpoints
            k_resp = await client.get(f"/api/v1/projects/{project.id}/knowledge", headers=headers)
            assert k_resp.status_code == 200
            k_data = k_resp.json()
            assert k_data["version"] == 1
            assert k_data["project_id"] == str(project.id)

            # Update product model
            k_put = await client.put(
                f"/api/v1/projects/{project.id}/knowledge",
                json={"purpose": "Updated LMS purpose", "capabilities": [{"name": "submissions"}]},
                headers=headers,
            )
            assert k_put.status_code == 200
            assert k_put.json()["version"] == 2

            # 5. List historical validation runs
            vlist_resp = await client.get(f"/api/v1/projects/{project.id}/validations", headers=headers)
            assert vlist_resp.status_code == 200
            assert len(vlist_resp.json()) == 1
    finally:
        app.dependency_overrides.clear()


def test_cli_exit_code_contract():
    # Test exit code 3 on missing configuration
    args_bad = argparse.Namespace(
        api_url=None, api_token=None, project_id=None, changed_files=None,
        diff_file=None, commit_sha=None, branch=None, pr_number=None,
        base_url=None, scope="targeted", commit_message=None, fail_on_healed=False,
        json_output=False, timeout=10, interval=1
    )
    assert run_ci(args_bad) == 3

    # Test exit code 4 on infrastructure connection failure
    args_offline = argparse.Namespace(
        api_url="http://127.0.0.1:59999", api_token="tok_123", project_id=str(uuid.uuid4()),
        changed_files=None, diff_file=None, commit_sha=None, branch=None,
        pr_number=None, base_url=None, scope="targeted", commit_message=None,
        fail_on_healed=False, json_output=False, timeout=10, interval=1
    )
    assert run_ci(args_offline) == 4

    # Test exit code 0 when all product flows pass
    mock_run_data = {
        "id": str(uuid.uuid4()),
        "status": "PASSED",
        "exit_code": 0,
        "selected_flow_ids": ["f1"],
        "summary": {"total_flows": 1, "passed": 1, "failed": 0},
    }
    with patch("scripts.kova_ci._http_request") as mock_http:
        mock_http.side_effect = [
            (201, {"id": mock_run_data["id"], "selected_flow_ids": ["f1"]}),  # validate POST
            (200, mock_run_data),  # poll GET
            (200, mock_run_data),  # report GET
        ]
        args_passed = argparse.Namespace(
            api_url="http://mock", api_token="tok", project_id=str(uuid.uuid4()),
            changed_files="a.py", diff_file=None, commit_sha="abc", branch="main",
            pr_number=None, base_url=None, scope="targeted", commit_message=None,
            fail_on_healed=False, json_output=True, timeout=10, interval=0.1
        )
        assert run_ci(args_passed) == 0

    # Test exit code 1 when required flows fail
    mock_failed_data = {
        "id": str(uuid.uuid4()),
        "status": "FAILED",
        "exit_code": 1,
        "selected_flow_ids": ["f1"],
        "summary": {"total_flows": 1, "passed": 0, "failed": 1},
    }
    with patch("scripts.kova_ci._http_request") as mock_http:
        mock_http.side_effect = [
            (201, {"id": mock_failed_data["id"], "selected_flow_ids": ["f1"]}),
            (200, mock_failed_data),
            (200, mock_failed_data),
        ]
        assert run_ci(args_passed) == 1

    # Test exit code 2 when blocked or unverified
    mock_blocked_data = {
        "id": str(uuid.uuid4()),
        "status": "BLOCKED",
        "exit_code": 2,
        "selected_flow_ids": ["f1"],
        "summary": {"total_flows": 1, "passed": 0, "blocked": 1},
    }
    with patch("scripts.kova_ci._http_request") as mock_http:
        mock_http.side_effect = [
            (201, {"id": mock_blocked_data["id"], "selected_flow_ids": ["f1"]}),
            (200, mock_blocked_data),
            (200, mock_blocked_data),
        ]
        assert run_ci(args_passed) == 2
