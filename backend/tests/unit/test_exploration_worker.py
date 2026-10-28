"""Unit tests for the Celery-based exploration worker task."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.exploration.models import ExplorationStatus
from app.workers.tasks.exploration import run_exploration, _run_exploration_async


@pytest.fixture(autouse=True)
def bind_worker_to_test_database(db_session, monkeypatch):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(
        "app.infrastructure.database.session.async_session_factory", factory
    )
    from app.engine.execution import control

    async def no_redis():
        return None

    async def no_commands(_session_id):
        if False:
            yield {}

    monkeypatch.setattr(control, "_get_redis", no_redis)
    monkeypatch.setattr(control, "subscribe_commands", no_commands)


async def _create_session(db_session, *, status=ExplorationStatus.CREATED, url="https://example.com", goal=None):
    from app.modules.exploration.repository import ExplorationRepository
    from app.modules.users.models import User

    user = User(email=f"worker-{uuid.uuid4()}@example.com")
    db_session.add(user)
    await db_session.flush()
    repo = ExplorationRepository(db_session)
    session = await repo.create(user_id=user.id, url=url, goal=goal)
    if status != ExplorationStatus.CREATED:
        await repo.update_status(session.id, status=status)
    await db_session.commit()
    return repo, session


@pytest.mark.asyncio
async def test_run_exploration_skips_terminal_session(db_session):
    """Worker should skip a session already in a terminal state."""
    repo, session = await _create_session(db_session)
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
    repo, session = await _create_session(db_session, status=ExplorationStatus.CONNECTING)

    result = await _run_exploration_async(None, str(session.id))
    assert result == {"status": "skipped", "reason": "already_claimed"}


@pytest.mark.asyncio
async def test_run_exploration_successful_explore(db_session, monkeypatch):
    """Worker should run the engine and persist results on success."""
    repo, session = await _create_session(db_session, goal="test goal")

    # Mock the engine
    mock_engine = MagicMock()
    mock_engine._browser = None
    mock_engine.cancel_background = MagicMock()
    mock_engine._get_budget_used = MagicMock(return_value={"pages_visited": 0, "actions": 0, "model_calls": 0, "wall_clock_seconds": 0})
    mock_engine._get_budget_limits = MagicMock(return_value={"max_wall_clock": 600, "max_pages": 50, "max_actions": 200, "max_model_calls": 100})
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
        "app.engine.exploration.explorer.ExplorationEngine", return_value=mock_engine
    ):
        result = await _run_exploration_async(None, str(session.id))

    assert result["status"] == "ready"
    assert result["session_id"] == str(session.id)

    # Verify session was updated
    await db_session.refresh(session)
    updated = await repo.get_by_id(session.id)
    assert updated.status == ExplorationStatus.READY.value
    assert len(updated.discoveries) == 1
    assert len(updated.candidate_missions) == 1
    assert updated.budget_used["wall_clock_seconds"] >= 0


@pytest.mark.asyncio
async def test_run_exploration_cancelled_before_start(db_session, monkeypatch):
    """Worker should honor cancellation before starting."""
    from app.engine.execution.control import request_cancel, cleanup_control
    repo, session = await _create_session(db_session)
    session_id = str(session.id)
    await cleanup_control(session_id)

    # Request cancellation before the worker starts
    await request_cancel(session_id, reason="test cancel")

    try:
        result = await _run_exploration_async(None, session_id)
        assert result == {"status": "cancelled", "session_id": session_id}

        await db_session.refresh(session)
        updated = await repo.get_by_id(uuid.UUID(session_id))
        assert updated.status == ExplorationStatus.CANCELLED.value
    finally:
        await cleanup_control(session_id)


@pytest.mark.asyncio
async def test_run_exploration_timeout(db_session, monkeypatch):
    """Worker should mark FAILED on exploration timeout."""
    repo, session = await _create_session(db_session)

    mock_engine = MagicMock()
    mock_engine._browser = None
    mock_engine.cancel_background = MagicMock()
    mock_engine._get_budget_used = MagicMock(return_value={"pages_visited": 0, "actions": 0, "model_calls": 0, "wall_clock_seconds": 0})
    mock_engine._get_budget_limits = MagicMock(return_value={"max_wall_clock": 600, "max_pages": 50, "max_actions": 200, "max_model_calls": 100})
    mock_engine.explore = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch(
        "app.engine.exploration.explorer.ExplorationEngine", return_value=mock_engine
    ), patch(
        "app.workers.tasks.exploration.asyncio.wait_for",
        side_effect=asyncio.TimeoutError(),
    ):
        result = await _run_exploration_async(None, str(session.id))

    assert result["status"] == "failed"
    assert result["reason"] == "budget_exhausted"

    await db_session.refresh(session)
    updated = await repo.get_by_id(session.id)
    assert updated.status == ExplorationStatus.FAILED.value
    assert "budget reached" in updated.error_message


@pytest.mark.asyncio
async def test_run_exploration_with_credential_resume(db_session, monkeypatch):
    """Worker should run exploration with provided credentials."""
    repo, session = await _create_session(
        db_session, status=ExplorationStatus.AUTHENTICATING, url="https://example.com/login"
    )

    mock_engine = MagicMock()
    mock_engine._browser = None
    mock_engine.cancel_background = MagicMock()
    mock_engine._get_budget_used = MagicMock(return_value={"pages_visited": 0, "actions": 0, "model_calls": 0, "wall_clock_seconds": 0})
    mock_engine._get_budget_limits = MagicMock(return_value={"max_wall_clock": 600, "max_pages": 50, "max_actions": 200, "max_model_calls": 100})
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
        "app.engine.exploration.explorer.ExplorationEngine", return_value=mock_engine
    ):
        from app.engine.execution.control import queue_user_input
        await queue_user_input(
            str(session.id),
            {"kind": "credentials", "email": "user@example.com", "password": "secret"},
        )
        result = await _run_exploration_async(None, str(session.id))

    assert result["status"] == "ready"
    # Verify the engine received the credential
    mock_engine.explore.assert_called_once_with(
        credential={"email": "user@example.com", "password": "secret"},
        selected_role=None,
        create_account=False,
    )


@pytest.mark.asyncio
async def test_pause_releases_worker_checkpoint_and_resume_requeues_session(db_session, monkeypatch):
    from app.modules.exploration import service as exploration_service
    from app.modules.exploration.service import ExplorationService

    repo, session = await _create_session(db_session, status=ExplorationStatus.EXPLORING)
    service = ExplorationService(db_session)
    monkeypatch.setattr(service, "_enqueue_exploration", AsyncMock())
    queued = []

    async def capture_input(session_id, payload):
        queued.append((session_id, payload))

    monkeypatch.setattr(exploration_service, "queue_worker_input", capture_input)

    paused = await service.pause_session(session.id, session.user_id)
    assert paused.status == ExplorationStatus.PAUSED.value

    resumed = await service.resume_session(session.id, session.user_id)
    assert resumed.status == ExplorationStatus.DISCOVERING.value
    service._enqueue_exploration.assert_awaited_once_with(session.id)
    assert queued == [(str(session.id), {"kind": "resume"})]


def test_exploration_task_does_not_accept_credentials_as_broker_arguments():
    from inspect import signature

    params = list(signature(run_exploration.run).parameters)
    assert params == ["session_id"]


def test_api_exploration_service_does_not_import_browser_runtime():
    import inspect
    from app.modules.exploration.service import ExplorationService

    source = inspect.getsource(ExplorationService)
    assert "BrowserSession" not in source
    assert "ExplorationEngine" not in source
    assert "playwright" not in source.lower()


@pytest.mark.asyncio
async def test_worker_input_fails_closed_without_shared_redis():
    from app.engine.execution.control import queue_worker_input

    with pytest.raises(RuntimeError, match="Shared worker control channel"):
        await queue_worker_input(str(uuid.uuid4()), {"kind": "answer", "selected_role": "member"})


@pytest.mark.parametrize(
    ("counter", "limit"),
    [
        ("_pages_visited_count", "max_pages"),
        ("_actions_count", "max_actions"),
        ("_model_calls", "max_model_calls"),
    ],
)
@pytest.mark.asyncio
async def test_exploration_budget_enforces_configured_work_caps(counter, limit):
    from app.engine.exploration.explorer import ExplorationEngine

    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://example.com")
    limits = {
        "max_wall_clock": 600,
        "max_pages": 5,
        "max_actions": 5,
        "max_model_calls": 5,
    }
    limits[limit] = 1
    engine._get_budget_limits = lambda: limits
    setattr(engine, counter, 1)

    allowed, reason = await engine._check_budget()
    assert allowed is False
    assert reason is not None
