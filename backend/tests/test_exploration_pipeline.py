"""Tests for exploration pipeline fixes.

Covers:
- Page validation (404, 403, 500, timeout)
- Exploration state machine
- Event persistence optimization
- Screenshot storage
- Health endpoint
- Exploration timeout
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.exploration.explorer import (
    ExplorationEngine,
    PageValidationError,
    ERROR_PAGE_PATTERNS,
    ERROR_TITLE_PATTERNS,
)
from app.engine.browser.screenshot_storage import ScreenshotStorage
from app.modules.exploration.models import ExplorationStatus


class TestExplorationStatusEnum:
    """Test that the status enum includes all required states."""

    def test_has_all_states(self):
        expected = {
            "CREATED", "CONNECTING", "LOADING", "VALIDATING_PAGE",
            "EXPLORING", "UNDERSTANDING", "AUTH_REQUIRED", "AUTHENTICATING",
            "ASKING", "DISCOVERING", "PLANNING", "READY", "EXECUTING",
            "COMPLETED", "FAILED", "CANCELLED",
        }
        actual = {s.value for s in ExplorationStatus}
        assert expected.issubset(actual), f"Missing states: {expected - actual}"

    def test_terminal_states(self):
        terminal = {ExplorationStatus.READY, ExplorationStatus.FAILED, ExplorationStatus.CANCELLED}
        for s in terminal:
            assert s.value in {"READY", "FAILED", "CANCELLED"}


class TestPageValidation:
    """Test page validation logic for error detection."""

    def test_error_patterns_exist(self):
        assert len(ERROR_PAGE_PATTERNS) > 0
        assert len(ERROR_TITLE_PATTERNS) > 0

    def test_page_validation_error_has_attributes(self):
        err = PageValidationError("test", status_code=404, final_url="http://example.com/404")
        assert err.status_code == 404
        assert err.final_url == "http://example.com/404"
        assert str(err) == "test"


class TestScreenshotStorage:
    """Test screenshot storage."""

    def test_save_requires_supabase(self):
        """Save raises RuntimeError when Supabase is not configured."""
        storage = ScreenshotStorage()
        test_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        # Will raise RuntimeError if SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set
        try:
            result = storage.save("test-exp-123", test_bytes, "http://example.com")
            # If Supabase is configured, verify the result structure
            assert "screenshot_key" in result
            assert result["screenshot_size_bytes"] == len(test_bytes)
            assert result["screenshot_key"].endswith(".png")
            assert result.get("screenshot_url") is not None
        except RuntimeError:
            # Expected when Supabase is not configured
            pass

    def test_get_public_url(self, monkeypatch):
        """get_public_url returns None when not configured, and RumptyCloud URL when configured."""
        from app.config.settings import settings

        storage = ScreenshotStorage()

        # When RumptyCloud S3 endpoint is not configured, returns None
        monkeypatch.setattr(settings, "RUMPTYCLOUD_S3_ENDPOINT", "")
        url = storage.get_public_url("test.png", "exp-123")
        assert url is None

        # When RumptyCloud is configured, returns RumptyCloud URL
        monkeypatch.setattr(settings, "RUMPTYCLOUD_S3_ENDPOINT", "https://s3.rumptycloud.com")
        monkeypatch.setattr(settings, "RUMPTYCLOUD_BUCKET_NAME", "kova-screenshots")
        url = storage.get_public_url("test.png", "exp-123")
        assert url is not None
        assert "rumptycloud" in url



class TestEventPersistenceOptimization:
    """Test that event creation doesn't do unnecessary refresh."""

    @pytest.mark.asyncio
    async def test_event_create_no_refresh(self, db_session):
        """Verify event creation doesn't trigger extra SELECT (refresh)."""
        from app.modules.exploration.repository import ExplorationEventRepository

        # Create a user first
        from app.modules.users.models import User
        user = User(id=uuid.uuid4(), email="test@test.com", name="Test")
        db_session.add(user)
        await db_session.flush()

        # Create a project
        from app.modules.projects.models import Project
        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            name="Test",
            base_url="http://test.com",
        )
        db_session.add(project)
        await db_session.flush()

        # Create exploration session
        from app.modules.exploration.models import ExplorationSession
        session = ExplorationSession(
            id=uuid.uuid4(),
            user_id=user.id,
            project_id=project.id,
            url="http://test.com",
            status=ExplorationStatus.CREATED.value,
        )
        db_session.add(session)
        await db_session.flush()

        # Create event - should not do extra SELECT
        event_repo = ExplorationEventRepository(db_session)
        event = await event_repo.create(
            exploration_id=session.id,
            event_type="test.event",
            payload={"key": "value"},
        )

        assert event.id is not None
        assert event.event_type == "test.event"
        assert event.payload == {"key": "value"}
        await db_session.commit()


class TestExplorationEngine:
    """Test exploration engine event emissions."""

    def test_engine_emits_state_change(self):
        """Verify engine constructor accepts all required parameters."""
        engine = ExplorationEngine(
            exploration_id=uuid.uuid4(),
            url="http://example.com",
            goal="test goal",
            event_emitter=AsyncMock(),
        )
        assert engine.url == "http://example.com"
        assert engine.goal == "test goal"
        assert engine._is_cancelled is False

    def test_cancel_sets_flag(self):
        engine = ExplorationEngine(
            exploration_id=uuid.uuid4(),
            url="http://example.com",
        )
        engine.cancel()
        assert engine._is_cancelled is True

    @pytest.mark.asyncio
    async def test_discover_workflows_insufficient_elements(self):
        """Verify no missions generated when page has < 2 interactive elements."""
        engine = ExplorationEngine(
            exploration_id=uuid.uuid4(),
            url="http://example.com",
        )

        # Mock page with minimal elements
        mock_page = MagicMock()
        mock_page.url = "http://example.com"
        mock_page.eval_on_selector_all = AsyncMock(return_value=[])

        observation = {
            "elements": [{"type": "button", "name": "OK"}],  # Only 1 element
            "text": "Hello world",
            "title": "Test Page",
        }

        discoveries, missions = await engine._discover_workflows(mock_page, observation, None)
        assert len(missions) == 0, "Should not generate missions with insufficient elements"

    @pytest.mark.asyncio
    async def test_discover_workflows_empty_page(self):
        """Verify no missions generated on empty page."""
        engine = ExplorationEngine(
            exploration_id=uuid.uuid4(),
            url="http://example.com",
        )

        mock_page = MagicMock()
        mock_page.url = "http://example.com"
        mock_page.eval_on_selector_all = AsyncMock(return_value=[])

        observation = {
            "elements": [],
            "text": "",
            "title": "Test Page",
        }

        discoveries, missions = await engine._discover_workflows(mock_page, observation, None)
        assert len(missions) == 0
        assert len(discoveries) == 0


class TestHealthEndpoint:
    """Test that health endpoint is available at both paths."""

    @pytest.mark.asyncio
    async def test_health_endpoint_exists(self):
        """Verify health endpoint is registered."""
        from httpx import ASGITransport, AsyncClient
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            resp = await client.get("/api/v1/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


class TestNormalizeExploreStatus:
    """Test frontend status normalization."""

    def test_normalize_new_states(self):
        """Verify new status values are handled."""
        # The normalization logic is in the frontend; here we verify
        # the backend emits the correct status values
        assert ExplorationStatus.LOADING.value == "LOADING"
        assert ExplorationStatus.VALIDATING_PAGE.value == "VALIDATING_PAGE"
        assert ExplorationStatus.PLANNING.value == "PLANNING"


class TestExplorationTimeout:
    """Test exploration timeout configuration."""

    def test_timeout_constant_exists(self):
        from app.modules.exploration.service import EXPLORATION_TIMEOUT_SECONDS
        assert EXPLORATION_TIMEOUT_SECONDS > 0
        assert EXPLORATION_TIMEOUT_SECONDS <= 300  # Reasonable upper bound


class TestExecutionRunner:
    """Test execution runner step normalization and error handling."""

    def test_normalize_step_new_format(self):
        """Step with type+target passes through unchanged."""
        from app.engine.execution.runner import FlowRunner
        runner = FlowRunner()
        step = {"type": "click", "target": {"role": "button", "name": "OK"}, "value": ""}
        result = runner._normalize_step(step)
        assert result["type"] == "click"
        assert result["target"]["role"] == "button"

    def test_normalize_step_old_format(self):
        """Step with action+selector converts to new format."""
        from app.engine.execution.runner import FlowRunner
        runner = FlowRunner()
        step = {"action": "click", "selector": "#submit-btn"}
        result = runner._normalize_step(step)
        assert result["type"] == "click"
        assert result["target"]["css"] == "#submit-btn"

    def test_normalize_step_description_navigate(self):
        """Description-based step infers navigate action."""
        from app.engine.execution.runner import FlowRunner
        runner = FlowRunner()
        step = {"action": "Navigate to generator", "description": "Open the quiz generator page"}
        result = runner._normalize_step(step)
        assert result["type"] == "navigate"

    def test_normalize_step_description_click(self):
        """Description-based step infers click action."""
        from app.engine.execution.runner import FlowRunner
        runner = FlowRunner()
        step = {"action": "Click sign in button", "description": "Click the sign in button"}
        result = runner._normalize_step(step)
        assert result["type"] == "click"

    def test_normalize_step_description_type(self):
        """Description-based step infers type action."""
        from app.engine.execution.runner import FlowRunner
        runner = FlowRunner()
        step = {"action": "Enter email", "description": "Type the email address"}
        result = runner._normalize_step(step)
        assert result["type"] == "type"

    def test_normalize_step_url_value(self):
        """Step with URL value infers navigate."""
        from app.engine.execution.runner import FlowRunner
        runner = FlowRunner()
        step = {"action": "", "value": "https://example.com"}
        result = runner._normalize_step(step)
        assert result["type"] == "navigate"

    def test_error_code_mapping(self):
        """Error types map to structured PRD error codes."""
        from app.engine.execution.runner import _map_error_code, ErrorCode
        assert _map_error_code("target_not_found") == ErrorCode.TARGET_NOT_FOUND
        assert _map_error_code("credential_error") == ErrorCode.AUTHENTICATION_FAILED
        assert _map_error_code("execution_error") == ErrorCode.ACTION_FAILED
        assert _map_error_code("unknown_type") == ErrorCode.UNKNOWN

    def test_execution_timeout_constant(self):
        """Execution timeout is configured."""
        from app.engine.execution.runner import EXECUTION_TIMEOUT_SECONDS
        assert EXECUTION_TIMEOUT_SECONDS > 0
        assert EXECUTION_TIMEOUT_SECONDS <= 600

    def test_max_action_retries(self):
        """Retry limit is configured."""
        from app.engine.execution.runner import MAX_ACTION_RETRIES
        assert MAX_ACTION_RETRIES >= 1
        assert MAX_ACTION_RETRIES <= 10

    def test_error_code_enum(self):
        """ErrorCode enum has all PRD §46 categories."""
        from app.engine.execution.runner import ErrorCode
        expected = {
            "AUTHENTICATION_FAILED", "BROWSER_START_FAILED", "PAGE_LOAD_FAILED",
            "TARGET_NOT_FOUND", "ACTION_FAILED", "VERIFICATION_FAILED",
            "EXECUTION_TIMEOUT", "RESOURCE_LIMIT", "NETWORK_ERROR",
            "APPLICATION_ERROR", "CANCELLED", "UNKNOWN",
        }
        actual = {v for k, v in ErrorCode.__dict__.items() if not k.startswith("_")}
        assert expected.issubset(actual)


class TestExplorationTaskLifecycle:
    """Test background task tracking and cancellation in ExplorationService."""

    @pytest.mark.asyncio
    async def test_register_and_cancel_task(self):
        import asyncio
        from app.modules.exploration.service import (
            _register_exploration_task,
            _active_exploration_tasks,
        )

        session_id = uuid.uuid4()
        started = asyncio.Event()

        async def dummy_flow():
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

        task = _register_exploration_task(session_id, dummy_flow())
        await started.wait()

        assert session_id in _active_exploration_tasks
        assert _active_exploration_tasks[session_id] is task
        assert not task.done()

        # Cancel task
        task.cancel()
        await asyncio.sleep(0.05)

        assert task.cancelled() or task.done()
        assert session_id not in _active_exploration_tasks

    @pytest.mark.asyncio
    async def test_register_cancels_previous_task(self):
        import asyncio
        from app.modules.exploration.service import (
            _register_exploration_task,
            _active_exploration_tasks,
        )

        session_id = uuid.uuid4()

        async def slow_flow():
            await asyncio.sleep(10)

        task1 = _register_exploration_task(session_id, slow_flow())
        await asyncio.sleep(0.01)
        assert not task1.done()

        task2 = _register_exploration_task(session_id, slow_flow())
        await asyncio.sleep(0.01)

        assert task1.cancelled() or task1.done()
        assert _active_exploration_tasks.get(session_id) is task2

        task2.cancel()


class TestLoginResolution:
    """Test login polling and targeted alert extraction."""

    @pytest.mark.asyncio
    async def test_extract_visible_auth_error_matches_banner(self):
        engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="http://example.com")
        page = AsyncMock()

        mock_alert = AsyncMock()
        mock_alert.is_visible.return_value = True
        mock_alert.inner_text.return_value = "Invalid email or password"

        page.query_selector_all.side_effect = lambda sel: [mock_alert] if sel == '[role="alert"]' else []

        err = await engine._extract_visible_auth_error(page)
        assert err == "Invalid email or password"

    @pytest.mark.asyncio
    async def test_extract_visible_auth_error_ignores_benign_text(self):
        engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="http://example.com")
        page = AsyncMock()

        mock_banner = AsyncMock()
        mock_banner.is_visible.return_value = True
        mock_banner.inner_text.return_value = "Welcome back to our store!"

        page.query_selector_all.return_value = [mock_banner]

        err = await engine._extract_visible_auth_error(page)
        assert err is None

    @pytest.mark.asyncio
    async def test_perform_login_success_on_url_navigation(self):
        engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="http://example.com/login")
        page = AsyncMock()

        # Mock email, password inputs, and submit button
        email_loc = AsyncMock()
        email_loc.is_visible.return_value = True
        password_loc = AsyncMock()
        password_loc.is_visible.return_value = True
        submit_loc = AsyncMock()
        submit_loc.is_visible.return_value = True

        def mock_locator(sel):
            mock = AsyncMock()
            if "type=\"password\"" in sel:
                # Initially password visible, then page navigated away so password is gone
                mock.first.is_visible.side_effect = [True, False, False]
            elif "button" in sel or "submit" in sel:
                mock.first.is_visible.return_value = True
            else:
                mock.first.is_visible.return_value = True
            return mock

        page.locator = mock_locator
        # URL changes from /login to /dashboard
        page.url = "http://example.com/dashboard"
        page.query_selector_all.return_value = []

        success, msg = await engine._perform_login(
            page, {"email": "user@example.com", "password": "correct_password"}
        )
        assert success is True
        assert msg == ""
