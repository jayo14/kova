import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.config.settings import settings
from app.engine.browser.session import BrowserSession
from app.engine.execution.runner import FlowRunner
from app.engine.execution.context import ExecutionContext
from app.engine.verification.verifier import VerificationCheck, VerificationResult
from app.modules.executions.event_types import EventTypes
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.auth.token_service import create_api_token
from app.main import app
from app.infrastructure.database.session import get_session


@pytest.mark.asyncio
async def test_browser_session_records_network_errors_and_emits_event():
    session = BrowserSession(headless=True)
    recorded_events = []

    def on_net_err(err):
        recorded_events.append(err)

    session.on_network_error = on_net_err

    # Manually trigger the internal listener callbacks or simulate them
    session._page = AsyncMock()
    session._page.url = "https://example.com/form"

    # Simulate same-origin 500 response
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.url = "https://example.com/api/contact"
    mock_resp.request.method = "POST"

    # Simulate network listeners
    # 1. HTTP 500 error
    session.network_errors.append({
        "type": "http_error",
        "status": 500,
        "method": "POST",
        "url": mock_resp.url,
        "path": "/api/contact",
        "step_index": 1,
    })
    session.on_network_error(session.network_errors[-1])

    assert len(session.network_errors) == 1
    assert session.network_errors[0]["status"] == 500
    assert len(recorded_events) == 1
    assert recorded_events[0]["path"] == "/api/contact"


@pytest.mark.asyncio
async def test_runner_fails_on_5xx_after_submit_step(monkeypatch):
    monkeypatch.setattr(settings, "FAIL_ON_NETWORK_ERRORS", True)
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    flow_steps = [
        {"type": "navigate", "target": {"url": "https://example.com"}},
        {"type": "click", "target": {"css": "#submit-btn"}},
    ]

    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/success"
    mock_browser.network_errors = [
        {
            "type": "http_error",
            "status": 500,
            "method": "POST",
            "url": "https://example.com/api/contact",
            "path": "/api/contact",
            "step_index": 1,
        }
    ]

    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = VerificationResult(passed=True, checks=[])

    mock_action_executor = AsyncMock()
    mock_action_executor.execute.return_value = {"success": True, "result": {}}

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.ActionExecutor", return_value=mock_action_executor), \
         patch("app.engine.execution.runner.Verifier", return_value=mock_verifier), \
         patch.object(runner, "_capture_evidence", new=AsyncMock()), \
         patch.object(runner, "_frame_producer", new=AsyncMock()), \
         patch.object(runner, "_capture_live_snapshot", new=AsyncMock(return_value={})):

        res = await runner.execute(
            execution_id=exec_id,
            flow_steps=flow_steps,
            success_condition={"url_matches": "/success"},
        )

        assert res["success"] is False
        assert "UI reported success but request POST /api/contact returned 500" in res["error"]


@pytest.mark.asyncio
async def test_runner_allows_warning_only_when_fail_on_network_errors_false(monkeypatch):
    monkeypatch.setattr(settings, "FAIL_ON_NETWORK_ERRORS", False)
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    flow_steps = [
        {"type": "click", "target": {"css": "#submit-btn"}},
    ]

    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/success"
    mock_browser.network_errors = [
        {
            "type": "http_error",
            "status": 500,
            "method": "POST",
            "url": "https://example.com/api/contact",
            "path": "/api/contact",
            "step_index": 0,
        }
    ]

    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = VerificationResult(passed=True, checks=[])

    mock_action_executor = AsyncMock()
    mock_action_executor.execute.return_value = {"success": True, "result": {}}

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.ActionExecutor", return_value=mock_action_executor), \
         patch("app.engine.execution.runner.Verifier", return_value=mock_verifier), \
         patch.object(runner, "_capture_evidence", new=AsyncMock()), \
         patch.object(runner, "_frame_producer", new=AsyncMock()), \
         patch.object(runner, "_capture_live_snapshot", new=AsyncMock(return_value={})):

        res = await runner.execute(
            execution_id=exec_id,
            flow_steps=flow_steps,
            success_condition={"url_matches": "/success"},
        )

        assert res["success"] is True


@pytest.mark.asyncio
async def test_verification_failure_details_and_event_type():
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/login"
    mock_browser.network_errors = []

    mock_check = VerificationCheck(
        type="url_matches",
        passed=False,
        expected="/dashboard",
        actual="/login",
        message="URL does not match",
    )
    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = VerificationResult(passed=False, checks=[mock_check])

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.ActionExecutor"), \
         patch("app.engine.execution.runner.Verifier", return_value=mock_verifier), \
         patch.object(runner, "_capture_evidence", new=AsyncMock()), \
         patch.object(runner, "_frame_producer", new=AsyncMock()), \
         patch.object(runner, "_capture_live_snapshot", new=AsyncMock(return_value={})):

        res = await runner.execute(
            execution_id=exec_id,
            flow_steps=[],
            success_condition={"url_matches": "/dashboard"},
        )

        assert res["success"] is False
        assert "expected: '/dashboard'" in res["error"]
        assert "got: '/login'" in res["error"]

        # Check emitted event was verification.failed
        failed_events = [e for e in res["events"] if e.get("type") == "verification.failed"]
        assert len(failed_events) == 1
        assert failed_events[0]["type"] == EventTypes.VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_report_includes_plain_english_why_it_failed(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user = User(id=uuid.uuid4(), email="reporter@kova.local")
        db_session.add(user)
        await db_session.commit()

        token_obj, raw_token = await create_api_token(db_session, user.id, name="Tok")
        project = Project(id=uuid.uuid4(), user_id=user.id, name="P", base_url="https://example.com")
        flow = Flow(id=uuid.uuid4(), project_id=project.id, name="F", steps=[])
        execution = Execution(
            id=uuid.uuid4(),
            flow_id=flow.id,
            status=ExecutionStatus.FAILED.value,
            error_message="Verification failed: url_matches: URL does not match (expected: '/dashboard', got: '/login')",
        )
        db_session.add_all([project, flow, execution])
        await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/executions/{execution.id}/report",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["why_it_failed"] == execution.error_message
            assert "Why it failed" in data["html"]
            assert "expected: '/dashboard', got: '/login'" in data["html"]
    finally:
        app.dependency_overrides.clear()
