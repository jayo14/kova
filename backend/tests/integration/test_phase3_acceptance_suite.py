"""Phase 3 Comprehensive Controlled Acceptance Test Suite.

End-to-end verification of Phase 3 reliability, evidence-backed contracts,
multi-signal authentication, CRUD persistence, search verification,
validation errors, non-idempotent recovery guards, and report transparency.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import socket
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest
import uvicorn
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.database.base import Base
from app.engine.browser.session import BrowserSession
from app.engine.verification.verifier import Verifier
from app.engine.execution.context import ExecutionContext, ExecutionState
from app.engine.execution.runner import FlowRunner
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.event_model import ExecutionEvent
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.validation.models import ValidationRun, ValidationStatus
from app.modules.users.models import User
from tests.fixtures.acceptance_app import acceptance_app, reset_state, RECORDS, USERS, SESSIONS


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_controlled_server():
    reset_state()
    port = _get_free_port()
    config = uvicorn.Config(acceptance_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
        reset_state()


@pytest.fixture
async def controlled_server():
    async with _run_controlled_server() as url:
        yield url


@pytest.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_phase3_acceptance_comprehensive_suite(controlled_server, db_session):
    """Execute complete Phase 3 acceptance scenarios against the live application."""
    target_url = controlled_server

    # 1. Database and Project Setup
    user = User(
        id=uuid.uuid4(),
        email="phase3-lead@kova.local",
        name="Phase 3 Lead",
    )
    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Phase 3 Acceptance App",
        base_url=target_url,
    )
    db_session.add_all([user, project])
    await db_session.commit()

    async with BrowserSession() as session:
        page = session.page
        assert page is not None
        verifier = Verifier(page)

        # 2. Register a new user
        test_email = f"lead-{uuid.uuid4().hex[:6]}@kova.local"
        test_name = "Acceptance Lead"
        test_password = "SecurePassword123!"

        await page.goto(f"{target_url}/register", wait_until="networkidle")
        await page.fill("#name", test_name)
        await page.fill("#email", test_email)
        await page.fill("#password", test_password)
        await page.check("#terms_consent")
        await page.click("#btn-submit-register")
        await page.wait_for_url("**/dashboard**", timeout=10000)

        # 3. Multi-signal Authentication Verification
        auth_res = await verifier.verify({"auth_verified": True})
        assert auth_res.passed is True, f"Multi-signal auth check must pass: {auth_res.checks}"
        indicator_check = next((c for c in auth_res.checks if c.type == "auth_session_indicator"), None)
        assert indicator_check is not None
        assert indicator_check.passed is True
        assert indicator_check.details.get("selector") in ("a[href*='logout']", "#user-greeting", "#user-name", ".user-info")

        # 4. Create unique test record on /records/new
        await page.goto(f"{target_url}/records/new", wait_until="networkidle")
        record_title = f"Phase3 Record {uuid.uuid4().hex[:6]}"
        record_category = "feature"
        record_desc = "Verified persistence and multi-signal outcomes"

        await page.fill("#title", record_title)
        await page.select_option("#category", record_category)
        await page.fill("#description", record_desc)
        await page.click("#btn-submit-record")
        await page.wait_for_url("**/records**", timeout=10000)

        # 5. Verify record persistence in DOM
        crud_res = await verifier.verify({
            "record_persisted": {
                "title": record_title,
                "fields": {
                    "category": record_category,
                    "description": record_desc,
                },
            }
        })
        assert crud_res.passed is True, f"Record persisted check must pass: {crud_res.checks}"
        crud_check = crud_res.checks[0]
        assert crud_check.details.get("missing_fields") == []
        assert crud_check.details.get("missing_texts") == []

        # 6. Verify persistence across page reload
        reload_res = await verifier.verify({
            "record_persisted": {
                "title": record_title,
                "reload": True,
            }
        })
        assert reload_res.passed is True, f"Persistence across reload must pass: {reload_res.checks}"
        reload_check = reload_res.checks[0]
        assert reload_check.details.get("reloaded") is True

        # 7. Search for record: Positive match and negative exclusion
        await page.fill("#search-input", record_title)
        await page.click("#btn-filter")
        await page.wait_for_timeout(300)

        search_res = await verifier.verify({
            "search_results": {
                "query": record_title,
                "expected_matches": [record_title],
                "excluded_terms": ["Baseline System", "Payment Gateway"],
            }
        })
        assert search_res.passed is True, f"Search verification must pass: {search_res.checks}"
        search_check = search_res.checks[0]
        assert search_check.details.get("missing_expected") == []
        assert search_check.details.get("unexpected_present") == []

        # 8. Negative search: Nonexistent record
        await page.fill("#search-input", "NonExistentRecordXYZ999")
        await page.click("#btn-filter")
        await page.wait_for_timeout(300)

        neg_search_res = await verifier.verify({
            "search_results": {
                "query": "NonExistentRecordXYZ999",
                "expected_matches": [],
                "excluded_terms": [record_title],
            }
        })
        assert neg_search_res.passed is True, f"Negative search verification must pass: {neg_search_res.checks}"
        neg_search_check = neg_search_res.checks[0]
        assert neg_search_check.details.get("missing_expected") == []
        assert neg_search_check.details.get("unexpected_present") == []

        # 9. Validation error scenario: Invalid form submission
        await page.goto(f"{target_url}/records/new", wait_until="networkidle")
        await page.fill("#title", "x")  # Title too short (< 3 chars)
        await page.click("#btn-submit-record")
        await page.wait_for_timeout(300)

        val_res = await verifier.verify({
            "validation_error": {
                "expected_message": "at least 3 characters",
            }
        })
        assert val_res.passed is True, f"Validation error check must pass: {val_res.checks}"
        val_check = val_res.checks[0]
        assert val_check.passed is True

    # 10. Bounded recovery: Non-idempotent action safeguard
    runner = FlowRunner()
    ctx = ExecutionContext(
        execution_id=str(uuid.uuid4()),
        target_url=target_url,
    )
    ctx.state = ExecutionState.RUNNING

    non_idempotent_step = {
        "id": "step-pay",
        "action": "click",
        "target": {"selector": "#btn-submit-record"},
    }
    assert runner._is_non_idempotent_step(non_idempotent_step) is True

    recorded_events: list[dict] = []
    async def mock_event_recorder(*args, **kwargs):
        recorded_events.append({"args": args, "kwargs": kwargs})

    from app.engine.execution.runner import ErrorCode, ExecutionError
    mock_executor = AsyncMock()
    mock_executor.execute.side_effect = ExecutionError("Network timeout during submission", ErrorCode.ACTION_FAILED)

    mock_browser = AsyncMock()
    mock_browser.page.url = f"{target_url}/records/new"
    mock_browser.observe.return_value = {"text": "Creation form"}
    mock_browser.start_step_network_capture = MagicMock()

    # FlowRunner halts on non-idempotent action failure instead of blind replay
    with pytest.raises(ExecutionError) as exc_info:
        await runner._execute_step_with_retry(
            ctx=ctx,
            browser=mock_browser,
            action_executor=mock_executor,
            step=non_idempotent_step,
            step_index=0,
            event_recorder=mock_event_recorder,
        )

    assert exc_info.value.error_code == "NON_IDEMPOTENT_SUBMISSION_UNCERTAIN"
    assert any(e.get("type") == "action.idempotency_halted" for e in ctx.events)

    # 11. Final Report Breakdown and Denominator Transparency
    flow = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Phase 3 Verification Flow",
        steps=[{"action": "navigate", "url": target_url}],
    )
    execution = Execution(
        id=uuid.uuid4(),
        flow_id=flow.id,
        status=ExecutionStatus.COMPLETED.value,
    )
    db_session.add_all([flow, execution])
    await db_session.commit()

    # Record verified event with checks
    verification_payload = {
        "passed": True,
        "checks": [
            *[c.to_dict() for c in auth_res.checks],
            crud_check.to_dict(),
            reload_check.to_dict(),
            search_check.to_dict(),
            val_check.to_dict(),
        ],
    }
    event_rec = ExecutionEvent(
        execution_id=execution.id,
        event_type="verification.passed",
        payload=verification_payload,
    )
    db_session.add(event_rec)
    await db_session.commit()

    mock_request = MagicMock()
    mock_request.base_url = "http://testserver"

    from app.api.routes.executions import get_execution_report
    report_res = await get_execution_report(
        execution_id=str(execution.id),
        request=mock_request,
        format="json",
        user=user,
        db=db_session,
    )

    # Validate report metrics
    assert "verdict_breakdown" in report_res
    vb = report_res["verdict_breakdown"]
    assert vb["passed"] >= 5
    assert vb["failed"] == 0
    assert vb["blocked"] == 0
    assert vb["unverified"] == 0

    assert "assertions_summary" in report_res
    summary = report_res["assertions_summary"]
    assert summary["total_planned"] == summary["total_evaluated"]
    assert summary["total_evaluated"] >= 5
    assert summary["passed"] >= 5

    assert "recovery_audit_trail" in report_res
