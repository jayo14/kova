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

        from app.modules.executions.event_model import ExecutionEvent
        db_session.add(ExecutionEvent(
            execution_id=execution.id,
            event_type="verification.passed",
            payload={"checks": [{"type": "url", "passed": True, "expected": "/home", "actual": "/home"}]},
        ))
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
            expired = _generate_report_signature(execution.id, expires_at=1)
            assert not _verify_report_signature(execution.id, expired)

            # 2. Access signed HTML page publicly without token
            public_resp = await client.get(
                f"/api/v1/executions/{execution.id}/report?signature={sig}&format=html"
            )
            assert public_resp.status_code == 200
            assert "text/html" in public_resp.headers["content-type"]
            assert "Kova Execution Report" in public_resp.text
            assert "Report Flow" in public_resp.text

            incomplete = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
            db_session.add(incomplete)
            await db_session.commit()
            incomplete_resp = await client.get(
                f"/api/v1/executions/{incomplete.id}/report?format=json",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert incomplete_resp.json()["status"] == "UNVERIFIED"
            assert incomplete_resp.json()["persisted_status"] == "COMPLETED"
            assert incomplete_resp.json()["verification"]["passed"] is False

            # 3. Invalid signature rejected
            bad_resp = await client.get(
                f"/api/v1/executions/{execution.id}/report?signature=invalid_sig"
            )
            assert bad_resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_execution_report_shows_honest_ai_healing(db_session):
    from app.modules.executions.event_model import ExecutionEvent

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="healing-user@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="Healing Token")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", base_url="https://example.com")
        flow = Flow(id=uuid.uuid4(), project_id=project.id, name="F", steps=[])
        execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
        db_session.add_all([project, flow, execution])
        await db_session.commit()

        # Add ai_assisted event
        ev1 = ExecutionEvent(
            execution_id=execution.id,
            event_type="ai_assisted",
            payload={"step": 1, "alternate_target": "#repaired-button"},
        )
        db_session.add(ev1)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/executions/{execution.id}/report",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ai_healed_steps"] == 1
            assert "Passed with AI healing: 1 steps" in data["healing_summary"]
            assert "Passed with AI healing: 1 steps" in data["html"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ci_run_and_runner_fail_on_healed(db_session):
    from app.engine.execution.control import get_execution_fail_on_healed
    from app.engine.execution.runner import FlowRunner

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="ci-healed-user@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="CI Token")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", base_url="https://example.com")
        flow = Flow(id=uuid.uuid4(), project_id=project.id, name="F", steps=[])
        db_session.add_all([project, flow])
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/ci/run",
                json={
                    "project_id": str(project.id),
                    "flow_ids": [str(flow.id)],
                    "fail_on_healed": True,
                },
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert resp.status_code == 201
            data = resp.json()
            exec_id = data["executions"][0]["id"]
            flag = await get_execution_fail_on_healed(exec_id)
            assert flag is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_generate_validation_report_html():
    from app.modules.executions.reporting import ReportGenerator
    from app.modules.validation.schemas import (
        FlowValidationResult,
        ImpactReport,
        ValidationReport,
        ValidationRequest,
    )

    flow_id = uuid.uuid4()
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["app/routes/checkout.py"],
    )
    impact = ImpactReport(
        changed_files=["app/routes/checkout.py"],
        affected_capabilities=["checkout"],
        graph_traversal_log=["[Impact] File app/routes/checkout.py mapped to capability checkout"],
        minimal_execution_plan={
            "steps": [
                {"flow_id": str(flow_id), "flow_name": "Checkout Flow", "role": "target"}
            ]
        },
    )
    results = [
        FlowValidationResult(
            flow_id=flow_id,
            flow_name="Checkout Flow",
            role="target",
            status="passed",
            duration_ms=120,
        )
    ]
    report = ValidationReport(
        id=uuid.uuid4(),
        request=req,
        impact_report=impact,
        results=results,
        overall_status="passed",
        duration_ms=120,
    )

    generator = ReportGenerator()
    html_output = await generator.generate_validation_report(report, project_name="E-Commerce")

    assert "Impact Summary" in html_output
    assert "app/routes/checkout.py" in html_output
    assert "Execution Plan" in html_output
    assert "Checkout Flow" in html_output
    assert "Feature: Checkout Flow" in html_output
    assert "Graph Traversal Audit Log" in html_output


@pytest.mark.asyncio
async def test_generate_validation_report_json():
    from app.modules.validation.schemas import (
        FlowValidationResult,
        ImpactReport,
        ValidationReport,
        ValidationRequest,
    )

    flow_id = uuid.uuid4()
    report = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=uuid.uuid4()),
        impact_report=ImpactReport(changed_files=["main.py"]),
        results=[
            FlowValidationResult(
                flow_id=flow_id,
                flow_name="Login Flow",
                role="target",
                status="passed",
            )
        ],
        overall_status="passed",
    )

    json_data = report.model_dump(mode="json")
    round_tripped = ValidationReport.model_validate(json_data)
    assert round_tripped.id == report.id
    assert round_tripped.overall_status == "passed"
    assert len(round_tripped.results) == 1
    assert round_tripped.results[0].flow_name == "Login Flow"


@pytest.mark.asyncio
async def test_generate_diff_report():
    from app.modules.executions.reporting import ReportGenerator
    from app.modules.validation.differ import ReportDiffer
    from app.modules.validation.schemas import (
        FlowValidationResult,
        ImpactReport,
        ValidationReport,
        ValidationRequest,
    )

    flow_id = uuid.uuid4()
    report_before = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=uuid.uuid4()),
        impact_report=ImpactReport(),
        results=[
            FlowValidationResult(
                flow_id=flow_id,
                flow_name="Payment Flow",
                role="target",
                status="passed",
            )
        ],
        overall_status="passed",
    )
    report_after = ValidationReport(
        id=uuid.uuid4(),
        request=ValidationRequest(project_id=uuid.uuid4()),
        impact_report=ImpactReport(),
        results=[
            FlowValidationResult(
                flow_id=flow_id,
                flow_name="Payment Flow",
                role="target",
                status="failed",
                failure_reason="Gateway timeout",
            )
        ],
        overall_status="failed",
    )

    diff = ReportDiffer.diff(report_before, report_after)
    assert diff.overall_status_changed is True
    assert len(diff.flows_changed) == 1
    assert diff.flows_changed[0].flow_id == flow_id
    assert diff.flows_changed[0].status_changed is True
    assert diff.flows_changed[0].status_before == "passed"
    assert diff.flows_changed[0].status_after == "failed"

    generator = ReportGenerator()
    html_diff = await generator.generate_diff_report(diff, project_name="Payment System")
    assert "Validation Comparison (Diff Mode)" in html_diff
    assert "Payment Flow" in html_diff
    assert "Flows Changed" in html_diff


@pytest.mark.asyncio
async def test_signed_url_validation(db_session):
    from app.modules.executions.reporting import generate_validation_signature
    from app.modules.validation.models import SignedUrlModel, ValidationReportModel
    from datetime import datetime, timezone, timedelta

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="signed-user@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Signed Project", base_url="https://example.com")
        val_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        report_row = ValidationReportModel(
            id=val_id,
            project_id=project.id,
            overall_status="passed",
            duration_ms=450,
            request={"project_id": str(project.id)},
            impact_report={"changed_files": []},
            results=[],
            evidence_summary={},
            started_at=now,
            finished_at=now,
        )
        db_session.add_all([user, project, report_row])
        await db_session.commit()

        sig = generate_validation_signature(val_id)
        expiry_ts = int(sig.split(".", 1)[0])
        signed_url = SignedUrlModel(
            id=uuid.uuid4(),
            validation_id=val_id,
            url=f"http://test/api/v1/validations/{val_id}/report?signature={sig}",
            signature=sig,
            expires_at=datetime.fromtimestamp(expiry_ts, tz=timezone.utc),
            created_by=user.id,
        )
        db_session.add(signed_url)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/validations/{val_id}/report?signature={sig}&format=html")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "Signed Project" in resp.text
            assert "Validation Report" in resp.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_signed_url_expired(db_session):
    from app.modules.executions.reporting import generate_validation_signature
    from app.modules.validation.models import ValidationReportModel
    from datetime import datetime, timezone

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="expired-user@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Expired Project", base_url="https://example.com")
        val_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        report_row = ValidationReportModel(
            id=val_id,
            project_id=project.id,
            overall_status="passed",
            duration_ms=450,
            request={"project_id": str(project.id)},
            impact_report={},
            results=[],
            evidence_summary={},
            started_at=now,
            finished_at=now,
        )
        db_session.add_all([user, project, report_row])
        await db_session.commit()

        # Generate signature with past expiry
        expired_sig = generate_validation_signature(val_id, expires_at=100)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/validations/{val_id}/report?signature={expired_sig}")
            assert resp.status_code == 403
            assert "expired" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_signed_url_revoked(db_session):
    from app.modules.executions.reporting import generate_validation_signature
    from app.modules.validation.models import SignedUrlModel, ValidationReportModel
    from datetime import datetime, timezone

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="revoked-user@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Revoked Project", base_url="https://example.com")
        val_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        report_row = ValidationReportModel(
            id=val_id,
            project_id=project.id,
            overall_status="passed",
            duration_ms=450,
            request={"project_id": str(project.id)},
            impact_report={},
            results=[],
            evidence_summary={},
            started_at=now,
            finished_at=now,
        )
        db_session.add_all([user, project, report_row])
        await db_session.commit()

        sig = generate_validation_signature(val_id)
        expiry_ts = int(sig.split(".", 1)[0])
        signed_url = SignedUrlModel(
            id=uuid.uuid4(),
            validation_id=val_id,
            url=f"http://test/api/v1/validations/{val_id}/report?signature={sig}",
            signature=sig,
            expires_at=datetime.fromtimestamp(expiry_ts, tz=timezone.utc),
            created_by=user.id,
        )
        db_session.add(signed_url)
        await db_session.commit()

        # Delete from signed_urls to revoke it
        await db_session.delete(signed_url)
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/validations/{val_id}/report?signature={sig}")
            assert resp.status_code == 403
            assert "revoked" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_execution_share_and_revoke(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="share-user@kova.local")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="Share Project", base_url="https://example.com")
        flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Share Flow", steps=[])
        execution = Execution(id=uuid.uuid4(), flow_id=flow.id, status=ExecutionStatus.COMPLETED.value)
        db_session.add_all([user, project, flow, execution])
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="Share Token")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Share execution report
            share_resp = await client.post(
                f"/api/v1/executions/{execution.id}/share",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert share_resp.status_code == 200
            share_data = share_resp.json()
            assert "url" in share_data
            assert "signature" in share_data
            sig = share_data["signature"]

            # 2. Access signed report publicly
            pub_resp = await client.get(f"/api/v1/executions/{execution.id}/report?signature={sig}&format=html")
            assert pub_resp.status_code == 200
            assert "text/html" in pub_resp.headers["content-type"]

            # 3. Revoke execution report
            del_resp = await client.delete(
                f"/api/v1/executions/{execution.id}/share",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert del_resp.status_code == 200
            assert del_resp.json()["status"] == "revoked"

            # 4. Access after revoke is 403
            revoked_resp = await client.get(f"/api/v1/executions/{execution.id}/report?signature={sig}&format=html")
            assert revoked_resp.status_code == 403
            assert "revoked" in revoked_resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()

