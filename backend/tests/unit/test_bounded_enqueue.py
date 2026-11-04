import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Response, status

from app.modules.exploration.models import ExplorationSession, ExplorationStatus
from app.modules.exploration.schemas import ExplorationCreate
from app.modules.exploration.service import ExplorationService
from app.api.routes.exploration import create_exploration
from app.workers.recovery import _exploration_recovery_action, reconcile_explorations


@pytest.mark.asyncio
async def test_bounded_enqueue_failure_sets_pending_dispatch():
    """Verify that when Celery apply_async fails or times out, session is saved as PENDING_DISPATCH."""
    mock_db = AsyncMock()
    mock_session = MagicMock(spec=ExplorationSession)
    mock_session.id = uuid.uuid4()
    mock_session.status = ExplorationStatus.CREATED.value
    mock_session.project_id = None
    mock_session.metadata_ = {}

    service = ExplorationService(mock_db)
    service.repo.get_by_id = AsyncMock(return_value=mock_session)
    service.repo.update_status = AsyncMock()

    with patch(
        "app.workers.tasks.exploration.run_exploration.apply_async",
        side_effect=TimeoutError("Broker timeout"),
    ):
        await service._enqueue_exploration(mock_session.id)

    # Status must have been updated to PENDING_DISPATCH
    service.repo.update_status.assert_called_with(
        mock_session.id,
        status=ExplorationStatus.PENDING_DISPATCH,
    )
    assert mock_session.status == ExplorationStatus.PENDING_DISPATCH.value
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_create_exploration_returns_202_on_pending_dispatch():
    """Verify that POST /exploration/ returns HTTP 202 Accepted when enqueue fails and status is PENDING_DISPATCH."""
    mock_db = AsyncMock()
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    response = Response()

    mock_session = MagicMock()
    mock_session.id = uuid.uuid4()
    mock_session.user_id = mock_user.id
    mock_session.project_id = None
    mock_session.url = "https://example.com"
    mock_session.goal = "test goal"
    mock_session.status = ExplorationStatus.PENDING_DISPATCH.value
    mock_session.selected_role = None
    mock_session.discoveries = []
    mock_session.candidate_missions = []
    mock_session.question = None
    mock_session.credential_request = None
    mock_session.error_message = None
    mock_session.queue_info = None
    mock_session.created_at = None
    mock_session.updated_at = None

    data = ExplorationCreate(url="https://example.com", goal="test goal")

    with patch.object(
        ExplorationService,
        "create_and_start_exploration",
        AsyncMock(return_value=mock_session),
    ), patch(
        "app.engine.worker_liveness.get_queued_status_payload",
        AsyncMock(return_value={"worker_alive": False, "message": "Queued"}),
    ):
        result = await create_exploration(data, response, mock_user, mock_db)

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert result.status == ExplorationStatus.PENDING_DISPATCH.value


def test_exploration_recovery_action_caps_attempts_with_queue_unavailable():
    """Verify that after 5 dispatch attempts, recovery action flags fail_queue_unavailable."""
    action = _exploration_recovery_action(
        status=ExplorationStatus.PENDING_DISPATCH.value,
        age_seconds=10.0,
        attempts=5,
    )
    assert action == "fail_queue_unavailable"


def test_exploration_recovery_action_backoff():
    """Verify that before backoff wait time elapses, recovery action is None."""
    action = _exploration_recovery_action(
        status=ExplorationStatus.PENDING_DISPATCH.value,
        age_seconds=1.0,  # Less than backoff wait
        attempts=1,
    )
    assert action is None
