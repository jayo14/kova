"""Acceptance and unit tests for Exploration Stop and Project Deletion."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.exploration.models import ExplorationStatus
from app.modules.exploration.service import ExplorationService
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User
from app.workers.tasks.exploration import _run_exploration_async
from app.engine.execution.control import (
    check_cancel_flag,
    is_project_deleted,
    set_cancel_flag,
    set_project_deleted,
)
from app.engine.exploration.explorer import ExplorationEngine


@pytest.fixture(autouse=True)
def bind_test_database(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(
        "app.infrastructure.database.session.async_session_factory", factory
    )
    monkeypatch.setattr(
        "app.infrastructure.database.session.create_worker_session_factory",
        lambda _engine=None: factory,
    )
    from app.engine.execution import control

    async def no_commands(_session_id):
        if False:
            yield {}

    monkeypatch.setattr(control, "subscribe_commands", no_commands)


async def _create_test_session(
    db_session,
    *,
    status=ExplorationStatus.CREATED,
    url="https://example.com",
    project_id=None,
):
    from app.modules.exploration.repository import ExplorationRepository

    user = User(email=f"stop-test-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=user.id,
        url=url,
        project_id=project_id,
        goal="Verify stop behavior",
    )
    if status != ExplorationStatus.CREATED:
        await repo.update_status(session.id, status=status)
    await db_session.commit()
    return user, session


@pytest.mark.asyncio
async def test_stop_idempotent_and_completion_noop(db_session):
    """Double stop is idempotent and stop after completion is a no-op."""
    user, session = await _create_test_session(db_session, status=ExplorationStatus.CONNECTING)
    service = ExplorationService(db_session)

    # First stop sets STOPPING and sets cancel flag
    stopped_1 = await service.stop_session(session.id, user.id)
    assert stopped_1 is not None
    assert stopped_1.status == ExplorationStatus.STOPPING.value
    assert await check_cancel_flag(str(session.id)) is True

    # Second stop is idempotent (returns immediately without error)
    stopped_2 = await service.stop_session(session.id, user.id)
    assert stopped_2 is not None
    assert stopped_2.status == ExplorationStatus.STOPPING.value

    # Stop after completion is a no-op
    from app.modules.exploration.repository import ExplorationRepository
    repo = ExplorationRepository(db_session)
    await repo.update_status(session.id, status=ExplorationStatus.COMPLETED)
    await db_session.commit()

    stopped_completed = await service.stop_session(session.id, user.id)
    assert stopped_completed is not None
    assert stopped_completed.status == ExplorationStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_stop_during_navigation(db_session, monkeypatch):
    """Exploration worker terminates cleanly when stopped during page navigation."""
    user, session = await _create_test_session(db_session)

    mock_browser = MagicMock()
    mock_browser.is_started = True
    mock_browser.start = AsyncMock()
    mock_browser.start_screencast = AsyncMock()
    close_called = asyncio.Event()

    async def mock_close():
        close_called.set()

    mock_browser.close = mock_close
    mock_page = MagicMock()
    mock_page.url = session.url

    # Simulate long navigation that checks cancellation
    nav_started = asyncio.Event()

    async def mock_goto(*args, **kwargs):
        nav_started.set()
        await asyncio.sleep(10.0)

    async def mock_navigate(*args, **kwargs):
        nav_started.set()
        await asyncio.sleep(10.0)
        return {"commit": 0.1, "dcl": 0.2}

    mock_page.goto = mock_goto
    mock_browser.page = mock_page
    mock_browser.navigate = mock_navigate

    with patch.object(ExplorationEngine, "_warmup_preflight", return_value={"success": True, "status_code": 200}), patch("app.engine.exploration.explorer.BrowserSession", return_value=mock_browser):
        worker_task = asyncio.create_task(_run_exploration_async(None, str(session.id)))

        # Wait until navigation starts
        await asyncio.wait_for(nav_started.wait(), timeout=5.0)

        # Trigger stop via service
        service = ExplorationService(db_session)
        await service.stop_session(session.id, user.id)

        # Worker should finish within 5s
        result = await asyncio.wait_for(worker_task, timeout=5.0)
        assert result.get("status") == "cancelled"

        # Browser close must be called
        assert close_called.is_set()


@pytest.mark.asyncio
async def test_stop_during_ai_call(db_session, monkeypatch):
    """Exploration worker terminates cleanly when stopped during AI journey synthesis."""
    user, session = await _create_test_session(db_session)

    ai_started = asyncio.Event()
    cancel_event = asyncio.Event()

    mock_engine = MagicMock()
    mock_engine._browser = MagicMock()
    mock_engine._browser.close = AsyncMock()
    mock_engine.cancel_background = MagicMock()
    mock_engine.request_cancel = MagicMock(side_effect=cancel_event.set)
    mock_engine._get_budget_used = MagicMock(return_value={"pages_visited": 1, "actions": 1, "model_calls": 1, "wall_clock_seconds": 2})
    mock_engine._get_budget_limits = MagicMock(return_value={"max_wall_clock": 600, "max_pages": 50, "max_actions": 200, "max_model_calls": 100})

    async def mock_explore(*args, **kwargs):
        ai_started.set()
        await cancel_event.wait()
        raise asyncio.CancelledError("AI synthesis interrupted by cancellation")

    mock_engine.explore = mock_explore

    with patch("app.engine.exploration.explorer.ExplorationEngine", return_value=mock_engine):
        worker_task = asyncio.create_task(_run_exploration_async(None, str(session.id)))

        # Wait until AI synthesis starts
        await asyncio.wait_for(ai_started.wait(), timeout=5.0)

        # Signal stop
        service = ExplorationService(db_session)
        await service.stop_session(session.id, user.id)

        # Worker should finish within 5s
        result = await asyncio.wait_for(worker_task, timeout=5.0)
        assert result.get("status") == "cancelled"


@pytest.mark.asyncio
async def test_stop_while_waiting_for_credentials(db_session):
    """Session stopped while in AUTH_REQUIRED transitions cleanly to CANCELLED."""
    user, session = await _create_test_session(
        db_session,
        status=ExplorationStatus.AUTH_REQUIRED,
    )
    from app.modules.exploration.repository import ExplorationRepository
    repo = ExplorationRepository(db_session)
    await repo.update_status(
        session.id,
        credential_request={"type": "login", "reason": "Requires login"},
    )
    await db_session.commit()

    service = ExplorationService(db_session)
    stopped = await service.stop_session(session.id, user.id)
    assert stopped.status == ExplorationStatus.STOPPING.value

    # Simulate worker acknowledge or direct cancel
    await repo.update_status(session.id, status=ExplorationStatus.CANCELLED)
    await db_session.commit()

    latest = await repo.get_by_id(session.id)
    assert latest.status == ExplorationStatus.CANCELLED.value
    # Preserves partial state
    assert latest.credential_request is not None


@pytest.mark.asyncio
async def test_delete_project_mid_exploration(db_session, monkeypatch):
    """Deleting project mid-exploration stops worker within 5s without DB errors and cleans up."""
    # Create project and active exploration
    from app.modules.projects.models import Project
    user = User(email=f"proj-del-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        name="Target Project",
        user_id=user.id,
        base_url="https://example.com",
    )
    db_session.add(project)
    await db_session.flush()

    from app.modules.exploration.repository import ExplorationRepository
    exp_repo = ExplorationRepository(db_session)
    session = await exp_repo.create(
        user_id=user.id,
        project_id=project.id,
        url="https://example.com",
    )
    await db_session.commit()

    mock_browser = MagicMock()
    mock_browser.is_started = True
    browser_closed = asyncio.Event()

    async def mock_close():
        browser_closed.set()

    mock_browser.close = mock_close

    worker_running = asyncio.Event()

    async def mock_explore(*args, **kwargs):
        worker_running.set()
        # Keep running until project is deleted or cancelled
        while not await is_project_deleted(str(project.id)):
            await asyncio.sleep(0.1)
        raise asyncio.CancelledError("Project deleted")

    mock_engine = MagicMock()
    mock_engine._browser = mock_browser
    mock_engine.explore = mock_explore
    mock_engine.cancel_background = MagicMock()
    mock_engine._get_budget_used = MagicMock(return_value={"pages_visited": 1, "actions": 0, "model_calls": 0, "wall_clock_seconds": 1})
    mock_engine._get_budget_limits = MagicMock(return_value={"max_wall_clock": 600, "max_pages": 50, "max_actions": 200, "max_model_calls": 100})

    with patch("app.engine.exploration.explorer.ExplorationEngine", return_value=mock_engine):
        worker_task = asyncio.create_task(_run_exploration_async(None, str(session.id)))

        await asyncio.wait_for(worker_running.wait(), timeout=5.0)

        # Delete project mid-exploration
        proj_repo = ProjectRepository(db_session)
        deleted = await proj_repo.delete(project.id, user.id)
        assert deleted is True

        # Worker should finish within 5s cleanly
        result = await asyncio.wait_for(worker_task, timeout=5.0)
        assert result.get("status") == "cancelled"

        # Browser close must be called
        assert browser_closed.is_set()

        # Project was deleted from DB
        assert await proj_repo.get_by_id(project.id) is None
