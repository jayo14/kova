"""Unit tests for resilient auth barrier healing and multi-credential fallback in FlowRunner."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.engine.execution.runner import FlowRunner
from app.engine.credentials.store import CredentialStore
from app.engine.credentials.models import Credential as EngineCredential
from app.engine.verification.verifier import VerificationCheck, VerificationResult
from app.modules.credentials.repository import CredentialRepository
from app.modules.projects.models import Project
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_credential_repository_orders_by_created_at_desc(db_session):
    """Verify that CredentialRepository returns the most recently created credential first."""
    user = User(id=uuid.uuid4(), email=f"user-{uuid.uuid4().hex[:6]}@example.com", name="User")
    db_session.add(user)
    await db_session.flush()

    project = Project(id=uuid.uuid4(), user_id=user.id, name="Test Project", base_url="https://example.com")
    db_session.add(project)
    await db_session.flush()

    repo = CredentialRepository(db_session)
    c1 = await repo.create(project.id, name="old-cred", email="old@example.com", password="Pass1")
    c1.created_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await db_session.flush()

    c2 = await repo.create(project.id, name="new-cred", email="new@example.com", password="Pass2")
    c2.created_at = datetime.now(timezone.utc)
    await db_session.flush()
    await db_session.commit()

    creds = await repo.list_by_project(project.id)
    assert len(creds) >= 2
    assert creds[0].email == "new@example.com"
    assert creds[1].email == "old@example.com"


@pytest.mark.asyncio
async def test_runner_heals_auth_barrier_iterating_credentials():
    """Verify that when first credential fails, FlowRunner tries subsequent credentials until success."""
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    cred_store = CredentialStore()
    cred_store.add(EngineCredential(id="cred1", email="stale@example.com", password="WrongPassword!"))
    cred_store.add(EngineCredential(id="cred2", email="fresh@example.com", password="CorrectPassword!"))

    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/signin"
    mock_browser.page.title = AsyncMock(return_value="Dashboard")
    mock_browser.page.on = MagicMock()
    mock_browser.page.remove_listener = MagicMock()
    mock_browser.network_errors = []

    mock_action_executor = AsyncMock()
    mock_action_executor.execute.return_value = {"success": True, "result": {}}

    # Verifier reports auth mismatch on first attempt, then passes after healing
    mock_check_failed = VerificationCheck(
        type="url_matches",
        passed=False,
        expected="/dashboard",
        actual="https://example.com/signin",
        message="Current URL is signin",
    )
    mock_check_passed = VerificationCheck(
        type="url_matches",
        passed=True,
        expected="/dashboard",
        actual="https://example.com/dashboard",
        message="URL matches",
    )

    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = VerificationResult(passed=True, checks=[mock_check_passed])

    attempted_emails = []

    async def mock_perform_login(page, email, password, name=None, is_signup=False):
        attempted_emails.append(email)
        if email == "stale@example.com":
            return False, "Login rejected by application: Incorrect email or password."
        if email == "fresh@example.com":
            page.url = "https://example.com/dashboard"
            return True, "Authentication succeeded"
        return False, "Unknown user"

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.ActionExecutor", return_value=mock_action_executor), \
         patch("app.engine.execution.runner.Verifier", return_value=mock_verifier), \
         patch("app.engine.browser.auth.perform_login", side_effect=mock_perform_login), \
         patch.object(runner, "_capture_evidence", new=AsyncMock(return_value=True)), \
         patch.object(runner, "_frame_producer", new=AsyncMock()), \
         patch.object(runner, "_capture_live_snapshot", new=AsyncMock(return_value={})):

        res = await runner.execute(
            execution_id=exec_id,
            flow_steps=[{"type": "navigate", "target": {"url": "https://example.com/dashboard"}}],
            success_condition={"url_matches": "/dashboard"},
            credential_store=cred_store,
            target_url="https://example.com",
        )

        assert res["success"] is True
        # Verify both credentials were tried in order
        assert attempted_emails == ["stale@example.com", "fresh@example.com"]


@pytest.mark.asyncio
async def test_runner_heals_auth_barrier_with_auto_registration():
    """Verify that when no existing credentials succeed, FlowRunner falls back to automatic on-the-fly registration."""
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/signin"
    mock_browser.page.title = AsyncMock(return_value="Dashboard")
    mock_browser.page.on = MagicMock()
    mock_browser.page.remove_listener = MagicMock()
    mock_browser.network_errors = []

    mock_action_executor = AsyncMock()
    mock_action_executor.execute.return_value = {"success": True, "result": {}}

    mock_check_passed = VerificationCheck(
        type="url_matches",
        passed=True,
        expected="/dashboard",
        actual="https://example.com/dashboard",
        message="URL matches",
    )

    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = VerificationResult(passed=True, checks=[mock_check_passed])

    registered_users = []

    async def mock_perform_login(page, email, password, name=None, is_signup=False):
        if is_signup:
            registered_users.append(email)
            page.url = "https://example.com/dashboard"
            return True, "Account created"
        return False, "No valid login"

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.ActionExecutor", return_value=mock_action_executor), \
         patch("app.engine.execution.runner.Verifier", return_value=mock_verifier), \
         patch("app.engine.browser.auth.perform_login", side_effect=mock_perform_login), \
         patch.object(runner, "_capture_evidence", new=AsyncMock(return_value=True)), \
         patch.object(runner, "_frame_producer", new=AsyncMock()), \
         patch.object(runner, "_capture_live_snapshot", new=AsyncMock(return_value={})):

        res = await runner.execute(
            execution_id=exec_id,
            flow_steps=[{"type": "navigate", "target": {"url": "https://example.com/dashboard"}}],
            success_condition={"url_matches": "/dashboard"},
            credential_store=CredentialStore(),  # No credentials provided
            target_url="https://example.com",
        )

        assert res["success"] is True
        assert len(registered_users) == 1
        assert registered_users[0].startswith("kova-tester-")


@pytest.mark.asyncio
async def test_runner_heals_auth_barrier_during_post_verification():
    """Verify that if auth barrier is detected during post-execution verification, FlowRunner heals and re-verifies."""
    runner = FlowRunner()
    exec_id = uuid.uuid4()

    cred_store = CredentialStore()
    cred_store.add(EngineCredential(id="cred1", email="user@example.com", password="Pass!"))

    mock_browser = AsyncMock()
    mock_browser.page.url = "https://example.com/loading"
    mock_browser.page.title = AsyncMock(return_value="Loading")
    mock_browser.page.on = MagicMock()
    mock_browser.page.remove_listener = MagicMock()
    mock_browser.network_errors = []

    mock_action_executor = AsyncMock()
    mock_action_executor.execute.return_value = {"success": True, "result": {}}

    mock_check_failed = VerificationCheck(
        type="url_matches",
        passed=False,
        expected="/dashboard",
        actual="https://example.com/signin",
        message="Current URL is signin",
    )
    mock_check_passed = VerificationCheck(
        type="url_matches",
        passed=True,
        expected="/dashboard",
        actual="https://example.com/dashboard",
        message="URL matches",
    )

    mock_verifier = AsyncMock()
    mock_verifier.verify.side_effect = [
        VerificationResult(passed=False, checks=[mock_check_failed]),
        VerificationResult(passed=True, checks=[mock_check_passed]),
    ]

    attempted_logins = []

    async def mock_perform_login(page, email, password, name=None, is_signup=False):
        attempted_logins.append(email)
        page.url = "https://example.com/dashboard"
        return True, "Login successful"

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.ActionExecutor", return_value=mock_action_executor), \
         patch("app.engine.execution.runner.Verifier", return_value=mock_verifier), \
         patch("app.engine.browser.auth.perform_login", side_effect=mock_perform_login), \
         patch.object(runner, "_capture_evidence", new=AsyncMock(return_value=True)), \
         patch.object(runner, "_frame_producer", new=AsyncMock()), \
         patch.object(runner, "_capture_live_snapshot", new=AsyncMock(return_value={})):

        res = await runner.execute(
            execution_id=exec_id,
            flow_steps=[{"type": "navigate", "target": {"url": "https://example.com/loading"}}],
            success_condition={"url_matches": "/dashboard"},
            credential_store=cred_store,
            target_url="https://example.com",
        )

        assert res["success"] is True
        assert attempted_logins == ["user@example.com"]

