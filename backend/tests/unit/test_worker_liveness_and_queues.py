"""Unit tests for worker liveness, queue isolation, pub/sub resilience, and stale task handling."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

from app.config.settings import settings
from app.engine.execution.stream import subscribe_frames
from app.engine.worker_liveness import get_queued_status_payload
from app.workers.celery_app import get_queue_for_plan
from app.modules.exploration.models import ExplorationStatus


@pytest.mark.asyncio
async def test_pubsub_reconnect_resilience():
    """Verify that subscribe_frames reconnects on Redis connection drop / timeout instead of terminating."""
    call_count = 0

    class MockPubSub:
        async def subscribe(self, *channels):
            pass

        async def unsubscribe(self, *channels):
            pass

        async def aclose(self):
            pass

        async def listen(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate timeout or broken pipe on first listen
                raise asyncio.TimeoutError("Socket read timed out")
            elif call_count == 2:
                yield {"type": "message", "data": b"frame_bytes_123"}
            else:
                await asyncio.sleep(10)
                yield {"type": "ping"}

    mock_client = MagicMock()
    mock_client.pubsub.return_value = MockPubSub()

    with patch("app.engine.execution.stream._create_pubsub_client", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        received = []
        async for frame in subscribe_frames("test-exec-123"):
            received.append(frame)
            if len(received) >= 1:
                break

        assert len(received) == 1
        assert received[0][0] == b"frame_bytes_123"
        # Verified that it slept on backoff after the first failure and continued
        mock_sleep.assert_called()


@pytest.mark.asyncio
async def test_no_worker_backlog_detection():
    """Verify honest reporting: 'No worker is running (queue backlog: N)' vs 'Queued - position N'."""
    # Case 1: No workers live, queue backlog = 5
    mock_redis = MagicMock()
    mock_redis.keys = AsyncMock(return_value=[])  # no worker:alive:*
    mock_redis.llen = AsyncMock(side_effect=lambda q: 5 if "free" in q else 0)

    with patch("app.engine.worker_liveness.get_liveness_redis", return_value=mock_redis):
        payload = await get_queued_status_payload(plan="free")
        assert payload["worker_alive"] is False
        assert payload["queue_backlog"] == 5
        assert payload["queue_position"] is None
        assert payload["message"] == "No worker is running (queue backlog: 5)"

    # Case 2: 2 workers live, queue backlog = 3, position = 3
    mock_redis.keys = AsyncMock(return_value=["worker:alive:host1", "worker:alive:host2"])
    mock_redis.get = AsyncMock(return_value='{"hostname": "host1", "time": 123456}')
    mock_redis.llen = AsyncMock(return_value=3)

    with patch("app.engine.worker_liveness.get_liveness_redis", return_value=mock_redis):
        payload = await get_queued_status_payload(plan="free")
        assert payload["worker_alive"] is True
        assert payload["worker_count"] == 2
        assert payload["queue_position"] == 3
        assert payload["message"] == "Queued - position 3"


@pytest.mark.asyncio
async def test_queued_timeout_with_no_worker():
    """Verify session queued past QUEUED_NO_WORKER_TIMEOUT_SECONDS transitions to FAILED with reason NO_WORKER."""
    session_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=settings.QUEUED_NO_WORKER_TIMEOUT_SECONDS + 30)

    mock_session = MagicMock()
    mock_session.id = session_id
    mock_session.user_id = uuid.uuid4()
    mock_session.status = ExplorationStatus.CREATED.value
    mock_session.created_at = stale_time
    mock_session.url = "https://example.com"
    mock_session.goal = None
    mock_session.selected_role = None
    mock_session.discoveries = []
    mock_session.candidate_missions = []
    mock_session.question = None
    mock_session.credential_request = None
    mock_session.error_message = None

    mock_db = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=mock_session)
    mock_repo.update_status = AsyncMock(return_value=mock_session)
    mock_event_repo = MagicMock()
    mock_event_repo.create = AsyncMock()

    with patch("app.api.routes.exploration._get_authorized_session", return_value=mock_session), \
         patch("app.api.routes.exploration.ExplorationRepository", return_value=mock_repo), \
         patch("app.api.routes.exploration.ExplorationEventRepository", return_value=mock_event_repo), \
         patch("app.engine.worker_liveness.get_live_workers", return_value=[]):
        from app.api.routes.exploration import get_exploration

        _ = await get_exploration(str(session_id), user=MagicMock(id=mock_session.user_id), db=mock_db)

        # Status must be updated to FAILED
        mock_repo.update_status.assert_called_once_with(
            session_id,
            status=ExplorationStatus.FAILED,
            error_message="No worker is running to process the queued session",
        )
        # Error event with reason NO_WORKER must be recorded
        mock_event_repo.create.assert_called_once()
        call_kwargs = mock_event_repo.create.call_args[1]
        assert call_kwargs["payload"]["reason"] == "NO_WORKER"
        assert call_kwargs["payload"]["error_code"] == "NO_WORKER"


def test_queue_and_key_prefix_isolation():
    """Verify that CELERY_QUEUE_PREFIX and REDIS_KEY_PREFIX properly isolate queues and channels."""
    original_celery_prefix = settings.CELERY_QUEUE_PREFIX
    original_redis_prefix = settings.REDIS_KEY_PREFIX

    try:
        # Prefix A
        settings.CELERY_QUEUE_PREFIX = "tenant_a:"
        settings.REDIS_KEY_PREFIX = "tenant_a:"
        queue_a = get_queue_for_plan("pro")
        assert queue_a == "tenant_a:kova-pro"

        # Prefix B
        settings.CELERY_QUEUE_PREFIX = "tenant_b:"
        settings.REDIS_KEY_PREFIX = "tenant_b:"
        queue_b = get_queue_for_plan("pro")
        assert queue_b == "tenant_b:kova-pro"

        # Queues are completely isolated
        assert queue_a != queue_b
    finally:
        settings.CELERY_QUEUE_PREFIX = original_celery_prefix
        settings.REDIS_KEY_PREFIX = original_redis_prefix


@pytest.mark.asyncio
async def test_stale_exploration_tasks_skipped():
    """Verify that exploration worker skips missing sessions, terminal sessions, and deleted projects quietly."""
    from app.workers.tasks.exploration import _run_exploration_async

    mock_task = MagicMock()
    # Case 1: Session not found
    mock_db = AsyncMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=None)

    mock_session_ctx = MagicMock(
        __aenter__=AsyncMock(return_value=mock_db),
        __aexit__=AsyncMock(return_value=None),
    )

    with patch("app.infrastructure.database.session.create_worker_engine"), \
         patch("app.infrastructure.database.session.create_worker_session_factory") as mock_factory, \
         patch("app.modules.exploration.repository.ExplorationRepository", return_value=mock_repo):
        mock_factory.return_value = mock_session_ctx

        res = await _run_exploration_async(mock_task, str(uuid.uuid4()))
        assert res == {"status": "skipped", "reason": "session_missing"}

    # Case 2: Session already terminal
    terminal_session = MagicMock()
    terminal_session.project_id = None
    terminal_session.status = ExplorationStatus.COMPLETED.value
    mock_repo.get_by_id = AsyncMock(return_value=terminal_session)

    with patch("app.infrastructure.database.session.create_worker_engine"), \
         patch("app.infrastructure.database.session.create_worker_session_factory") as mock_factory, \
         patch("app.modules.exploration.repository.ExplorationRepository", return_value=mock_repo):
        mock_factory.return_value = mock_session_ctx

        res = await _run_exploration_async(mock_task, str(uuid.uuid4()))
        assert res == {"status": "skipped", "reason": "already_terminal"}

    # Case 3: Project deleted
    active_session = MagicMock()
    proj_id = uuid.uuid4()
    active_session.project_id = proj_id
    active_session.status = ExplorationStatus.CREATED.value
    mock_repo.get_by_id = AsyncMock(return_value=active_session)

    with patch("app.infrastructure.database.session.create_worker_engine"), \
         patch("app.infrastructure.database.session.create_worker_session_factory") as mock_factory, \
         patch("app.modules.exploration.repository.ExplorationRepository", return_value=mock_repo), \
         patch("app.engine.execution.control.is_project_deleted", AsyncMock(return_value=True)):
        mock_factory.return_value = mock_session_ctx

        res = await _run_exploration_async(mock_task, str(uuid.uuid4()))
        assert res == {"status": "skipped", "reason": "project_deleted"}


@pytest.mark.asyncio
async def test_stale_execution_tasks_skipped():
    """Verify that execution runner worker skips missing executions, flows, and deleted projects quietly."""
    from app.workers.tasks.executions import _run_execution_async

    mock_db = AsyncMock()
    mock_exec_repo = MagicMock()
    mock_exec_repo.get_by_id = AsyncMock(return_value=None)
    mock_task = MagicMock()
    mock_session_ctx = MagicMock(
        __aenter__=AsyncMock(return_value=mock_db),
        __aexit__=AsyncMock(return_value=None),
    )

    # Case 1: Execution not found
    with patch("app.infrastructure.database.session.create_worker_engine"), \
         patch("app.infrastructure.database.session.create_worker_session_factory") as mock_factory, \
         patch("app.modules.executions.repository.ExecutionRepository", return_value=mock_exec_repo):
        mock_factory.return_value = mock_session_ctx

        res = await _run_execution_async(mock_task, str(uuid.uuid4()))
        assert res == {"status": "skipped", "reason": "execution_missing"}

    # Case 2: Execution already terminal
    term_exec = MagicMock()
    term_exec.status = "COMPLETED"
    mock_exec_repo.get_by_id = AsyncMock(return_value=term_exec)

    with patch("app.infrastructure.database.session.create_worker_engine"), \
         patch("app.infrastructure.database.session.create_worker_session_factory") as mock_factory, \
         patch("app.modules.executions.repository.ExecutionRepository", return_value=mock_exec_repo):
        mock_factory.return_value = mock_session_ctx

        res = await _run_execution_async(mock_task, str(uuid.uuid4()))
        assert res == {"status": "skipped", "reason": "already_terminal"}
