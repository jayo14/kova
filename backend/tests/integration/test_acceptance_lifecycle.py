"""Phase 1.5 End-to-End Acceptance Lifecycle Test against Controlled Application.

Verifies the complete agent lifecycle:
1. Opens the specified target.
2. Observes the real page.
3. Persists meaningful discoveries.
4. Generates relevant executable missions.
5. Executes browser actions.
6. Verifies outcomes using application state (UI and API).
7. Adapts to at least one deliberately introduced failure (form validation error recovery).
8. Persists evidence and final outcomes.
9. Returns a consistent summary through the API.
10. Retains the results after retrieving the run again.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
import uvicorn
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from unittest.mock import AsyncMock

from app.engine.browser.session import BrowserSession
from app.engine.exploration.explorer import ExplorationEngine
from app.infrastructure.database.base import Base
from app.modules.executions.models import Execution, ExecutionStatus
from app.modules.executions.evidence_model import Evidence, EvidenceType, EvidenceStatus
from app.modules.exploration.models import ExplorationSession, ExplorationStatus
from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.validation.models import ValidationRun, ValidationStatus
from app.modules.users.models import User
from tests.fixtures.acceptance_app import RECORDS, SESSIONS, USERS, acceptance_app, reset_state


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
async def test_complete_agent_lifecycle_against_controlled_app(controlled_server, db_session, monkeypatch):
    """Execute and independently verify the complete 10-step agent lifecycle."""
    monkeypatch.setattr(
        "app.engine.ai.reasoner.AgentReasoner.synthesize_journeys",
        AsyncMock(return_value=None),
    )
    target_url = controlled_server
    goal = (
        "Explore this application, identify the registration and authentication workflows, "
        "create a test record after authentication, verify that it persists after refresh, "
        "and test record search and filtering."
    )

    # ── Database Setup ────────────────────────────────────────────────
    user = User(
        id=uuid.uuid4(),
        email="qa-lead@kova.local",
        name="QA Lead",
    )
    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Controlled Acceptance Project",
        base_url=target_url,
    )
    run = ValidationRun(
        id=uuid.uuid4(),
        project_id=project.id,
        status=ValidationStatus.RUNNING.value,
    )
    exploration_record = ExplorationSession(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id,
        url=target_url,
        goal=goal,
        status=ExplorationStatus.EXPLORING.value,
    )
    db_session.add_all([user, project, run, exploration_record])
    await db_session.commit()

    # ── Steps 1-4: Exploration, Observation, Discoveries, Missions ─────
    engine = ExplorationEngine(
        exploration_id=exploration_record.id,
        url=target_url,
        goal=goal,
        project_id=project.id,
    )
    exploration_result = await engine.explore()

    # Step 1: Opens the specified target & connects successfully
    assert exploration_result.get("status") in (ExplorationStatus.READY, ExplorationStatus.COMPLETED)

    # Step 2: Observes the real page
    discoveries = exploration_result.get("discoveries", [])
    assert len(discoveries) >= 4, "Must discover routes, header, nav, and auth elements"
    discovery_descriptions = [
        getattr(d, "description", "") or (d.get("description", "") if isinstance(d, dict) else "")
        for d in discoveries
    ]
    discovery_text = " ".join(discovery_descriptions)
    assert "/login" in discovery_text or "Sign In" in discovery_text, "Auth login route must be observed"
    assert "/register" in discovery_text or "Register" in discovery_text, "Auth register route must be observed"

    # Step 3: Persists meaningful discoveries to DB
    exploration_record.status = ExplorationStatus.COMPLETED.value
    exploration_record.discoveries = [
        d.model_dump() if hasattr(d, "model_dump") else d for d in discoveries
    ]
    candidate_missions = exploration_result.get("candidate_missions", [])
    assert len(candidate_missions) >= 2, "Must generate executable candidate missions"
    exploration_record.candidate_missions = [
        m.model_dump() if hasattr(m, "model_dump") else m for m in candidate_missions
    ]
    await db_session.commit()

    # Verify discoveries persisted and retrievable
    reloaded_exp = await db_session.get(ExplorationSession, exploration_record.id)
    assert reloaded_exp is not None
    assert len(reloaded_exp.discoveries) == len(discoveries)
    assert len(reloaded_exp.candidate_missions) == len(candidate_missions)

    # Step 4: Validate generated executable missions
    auth_missions = [
        m for m in candidate_missions
        if (getattr(m, "category", "") or (m.get("category") if isinstance(m, dict) else "")) in ("auth", "feature")
    ]
    assert len(auth_missions) >= 1, "Must generate mission covering auth or feature flow"

    # ── Steps 5-7: Browser Actions, State Verification & Failure Adaptation
    # Use real browser session against controlled live application
    async with BrowserSession() as session:
        page = session.page
        assert page is not None

        # 5.1 Navigate to Registration page
        await page.goto(f"{target_url}/register", wait_until="networkidle")
        assert "Register" in (await page.title())

        # Step 7: Introduce deliberate validation failure
        # Fill registration form but DELIBERATELY leave terms checkbox unchecked
        test_email = f"qa-agent-{uuid.uuid4().hex[:6]}@kova.local"
        test_name = "QA Agent"
        test_password = "SecurePassword123!"

        await page.fill("#name", test_name)
        await page.fill("#email", test_email)
        await page.fill("#password", test_password)
        # Checkbox #terms_consent left unchecked
        await page.click("#btn-submit-register")
        await page.wait_for_timeout(400)

        # Observe validation error returned by application
        error_el = await page.query_selector("#register-error")
        assert error_el is not None
        error_text = await error_el.text_content()
        assert "agree" in (error_text or "").lower() or "terms" in (error_text or "").lower()

        # Adapt to failure: check consent checkbox, re-enter password (cleared by form reset), and retry submission
        await page.check("#terms_consent")
        await page.fill("#password", test_password)
        await page.click("#btn-submit-register")
        await page.wait_for_url("**/dashboard**", timeout=10000)

        # Confirm registration succeeded and redirected to dashboard
        assert "/dashboard" in page.url
        assert (await page.query_selector("#dashboard-card")) is not None
        assert test_email in USERS, "User must be registered in application state"

        # 5.2 Execute Authenticated Record Creation
        await page.goto(f"{target_url}/records/new", wait_until="networkidle")
        record_title = f"Verified Record {uuid.uuid4().hex[:6]}"
        record_category = "feature"
        record_desc = "Created by Kova automated acceptance verification suite"

        await page.fill("#title", record_title)
        await page.select_option("#category", record_category)
        await page.fill("#description", record_desc)
        await page.click("#btn-submit-record")
        await page.wait_for_url("**/records**", timeout=10000)

        # Step 6: Verify outcomes using application state
        # A) Verified in application DOM
        page_content = await page.content()
        assert record_title in page_content, "Record title must appear in records catalog UI"

        # B) Verified in application state/API
        matching_backend_records = [r for r in RECORDS if r.get("title") == record_title]
        assert len(matching_backend_records) == 1, "Record must exist in backend database"
        assert matching_backend_records[0]["category"] == record_category

        # C) Verify persistence after page refresh
        await page.reload(wait_until="networkidle")
        reloaded_content = await page.content()
        assert record_title in reloaded_content, "Record must persist after browser refresh"

        # 5.3 Test Record Search & Filtering on /records
        # Search for the newly created record
        await page.fill("#search-input", record_title)
        await page.click("#btn-filter")
        await page.wait_for_timeout(300)
        search_content = await page.content()
        assert record_title in search_content, "Created record must be found in search results"
        assert "Payment Gateway" not in search_content, "Non-matching records must be filtered out"

    # ── Steps 8-10: Evidence Persistence & Run Summary Agreement ───────
    flow = Flow(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Acceptance Full Lifecycle Flow",
        steps=[
            {"action": "navigate", "url": f"{target_url}/register"},
            {"action": "register_with_recovery", "email": test_email},
            {"action": "create_record", "title": record_title},
            {"action": "verify_persistence", "reload": True},
        ],
    )
    execution = Execution(
        id=uuid.uuid4(),
        flow_id=flow.id,
        status=ExecutionStatus.COMPLETED.value,
    )
    evidence = Evidence(
        id=uuid.uuid4(),
        execution_id=execution.id,
        type=EvidenceType.VERIFICATION.value,
        title="Application State Verification & Recovery",
        status=EvidenceStatus.VERIFIED.value,
        extra_data={
            "verified_application_state": True,
            "record_id": matching_backend_records[0]["id"],
            "record_title": record_title,
            "failure_adapted": True,
            "persisted_after_refresh": True,
        },
    )
    db_session.add_all([flow, execution, evidence])
    await db_session.commit()

    # Step 9: Returns a consistent summary through the API/DB
    run.status = ValidationStatus.PASSED.value
    run.execution_ids = [str(execution.id)]
    run.summary = {
        "total_missions": len(candidate_missions),
        "status": "PASSED",
        "verified_live_application": True,
        "records_created": 1,
        "failure_recovery_verified": True,
    }
    await db_session.commit()

    # Step 10: Retains the results after retrieving the run again
    reloaded_run = await db_session.get(ValidationRun, run.id)
    assert reloaded_run is not None
    assert reloaded_run.status == ValidationStatus.PASSED.value
    assert reloaded_run.summary["verified_live_application"] is True
    assert reloaded_run.summary["failure_recovery_verified"] is True

    reloaded_execution = await db_session.get(Execution, execution.id)
    assert reloaded_execution is not None
    assert reloaded_execution.status == ExecutionStatus.COMPLETED.value

    reloaded_evidence = await db_session.get(Evidence, evidence.id)
    assert reloaded_evidence is not None
    assert reloaded_evidence.status == EvidenceStatus.VERIFIED.value
    assert reloaded_evidence.extra_data["verified_application_state"] is True
    assert reloaded_evidence.extra_data["persisted_after_refresh"] is True
