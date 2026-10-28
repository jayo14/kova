"""Unit tests for the Celery-based exploration worker task."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.exploration.models import ExplorationStatus
from app.workers.tasks.exploration import run_exploration, _run_exploration_async


@pytest.mark.asyncio
async def test_run_exploration_skips_terminal_session(db_session):
    """Worker should skip a session already in a terminal state."""
    from app.modules.exploration.repository import ExplorationRepository

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com",
        goal=None,
    )
    await repo.update_status(
        session_id=session.id,
        status=ExplorationStatus.COMPLETED,
    )
    await db_session.commit()

    result = await _run_exploration_async(None, str(session.id))
    assert result == {"status": "skipped", "reason": "already_terminal"}


@pytest.mark.asyncio
async def test_run_exploration_skips_already_claimed_session(db_session):
    """Worker should skip a session already claimed (non-CREATED status)."""
    from app.modules.exploration.repository import ExplorationRepository

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com",
        goal=None,
    )
    await repo.update_status(
        session_id=session.id,
        status=ExplorationStatus.CONNECTING,
    )
    await db_session.commit()

    result = await _run_exploration_async(None, str(session.id))
    assert result == {"status": "skipped", "reason": "already_claimed"}


@pytest.mark.asyncio
async def test_run_exploration_successful_explore(db_session, monkeypatch):
    """Worker should run the engine and persist results on success."""
    from app.modules.exploration.repository import ExplorationRepository

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com",
        goal="test goal",
    )
    await db_session.commit()

    # Mock the engine
    mock_engine = MagicMock()
    mock_engine._browser = None
    mock_engine.cancel_background = MagicMock()
    mock_engine.explore = AsyncMock(
        return_value={
            "status": ExplorationStatus.READY,
            "discoveries": [{"label": "Get started", "description": "Home page"}],
            "candidate_missions": [
                {
                    "id": "mission-1",
                    "name": "Explore Get started",
                    "objective": "Navigate to Get started",
                    "steps": [],
                }
            ],
            "discovery_result": None,
            "brand_metadata": None,
        }
    )

    with patch(
        "app.workers.tasks.exploration.ExplorationEngine", return_value=mock_engine
    ):
        result = await _run_exploration_async(None, str(session.id))

    assert result["status"] == "ready"
    assert result["session_id"] == str(session.id)

    # Verify session was updated
    updated = await repo.get_by_id(session.id)
    assert updated.status == ExplorationStatus.READY.value
    assert len(updated.discoveries) == 1
    assert len(updated.candidate_missions) == 1


@pytest.mark.asyncio
async def test_run_exploration_cancelled_before_start(db_session, monkeypatch):
    """Worker should honor cancellation before starting."""
    from app.modules.exploration.repository import ExplorationRepository
    from app.engine.execution.control import request_cancel, cleanup_control

    session_id = str(uuid.uuid4())
    await cleanup_control(session_id)

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com",
        goal=None,
    )
    # Override the ID to match our cleanup_control key
    session.id = uuid.UUID(session_id)
    await repo.update_status(
        session_id=session.id,
        status=ExplorationStatus.CREATED,
    )
    await db_session.commit()

    # Request cancellation before the worker starts
    await request_cancel(session_id, reason="test cancel")

    try:
        result = await _run_exploration_async(None, session_id)
        assert result == {"status": "cancelled", "session_id": session_id}

        updated = await repo.get_by_id(uuid.UUID(session_id))
        assert updated.status == ExplorationStatus.CANCELLED.value
    finally:
        await cleanup_control(session_id)


@pytest.mark.asyncio
async def test_run_exploration_timeout(db_session, monkeypatch):
    """Worker should mark FAILED on exploration timeout."""
    from app.modules.exploration.repository import ExplorationRepository

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com",
        goal=None,
    )
    await db_session.commit()

    mock_engine = MagicMock()
    mock_engine._browser = None
    mock_engine.cancel_background = MagicMock()
    mock_engine.explore = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch(
        "app.workers.tasks.exploration.ExplorationEngine", return_value=mock_engine
    ), patch(
        "app.workers.tasks.exploration.asyncio.wait_for",
        side_effect=asyncio.TimeoutError(),
    ):
        result = await _run_exploration_async(None, str(session.id))

    assert result["status"] == "failed"
    assert result["reason"] == "timeout"

    updated = await repo.get_by_id(session.id)
    assert updated.status == ExplorationStatus.FAILED.value
    assert "timed out" in updated.error_message


@pytest.mark.asyncio
async def test_run_exploration_with_credential_resume(db_session, monkeypatch):
    """Worker should run exploration with provided credentials."""
    from app.modules.exploration.repository import ExplorationRepository

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com/login",
        goal=None,
    )
    await repo.update_status(
        session_id=session.id,
        status=ExplorationStatus.AUTHENTICATING,
    )
    await db_session.commit()

    mock_engine = MagicMock()
    mock_engine._browser = None
    mock_engine.cancel_background = MagicMock()
    mock_engine.explore = AsyncMock(
        return_value={
            "status": ExplorationStatus.READY,
            "discoveries": [],
            "candidate_missions": [],
            "discovery_result": None,
            "brand_metadata": None,
        }
    )

    with patch(
        "app.workers.tasks.exploration.ExplorationEngine", return_value=mock_engine
    ):
        result = await _run_exploration_async(
            None,
            str(session.id),
            credential={"email": "user@example.com", "password": "secret"},
        )

    assert result["status"] == "ready"
    # Verify the engine received the credential
    mock_engine.explore.assert_called_once_with(
        credential={"email": "user@example.com", "password": "secret"},
        selected_role=None,
        create_account=False,
    )


@pytest.mark.asyncio
async def test_run_exploration_celery_task_skips_terminal(db_session):
    """Celery task wrapper should skip terminal sessions via asyncio.run."""
    from app.modules.exploration.repository import ExplorationRepository

    repo = ExplorationRepository(db_session)
    session = await repo.create(
        user_id=uuid.uuid4(),
        url="https://example.com",
        goal=None,
    )
    await repo.update_status(
        session_id=session.id,
        status=ExplorationStatus.FAILED,
    )
    await db_session.commit()

    result = run_exploration.apply(args=(str(session.id),))
    assert result.result == {"status": "skipped", "reason": "already_terminal"}
