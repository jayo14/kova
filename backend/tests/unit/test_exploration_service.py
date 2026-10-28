"""Unit tests for the ExplorationService layer (task enqueuing)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.modules.exploration.models import ExplorationStatus
from app.modules.exploration.schemas import (
    ExplorationCreate,
    ExplorationCredentialSubmit,
    ExplorationCreateAccount,
    ExplorationAnswerSubmit,
)
from app.modules.exploration.service import ExplorationService
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_create_enqueues_exploration_task(db_session):
    """create_and_start_exploration should create a session and enqueue a worker task."""
    service = ExplorationService(db_session)

    enqueued = {}

    async def mock_enqueue(session_id, credential=None, selected_role=None, create_account=False):
        enqueued["session_id"] = session_id
        enqueued["credential"] = credential
        enqueued["selected_role"] = selected_role
        enqueued["create_account"] = create_account

    with patch.object(ExplorationService, "_enqueue_exploration", side_effect=mock_enqueue):
        session = await service.create_and_start_exploration(
            ExplorationCreate(url="https://example.com", goal="test goal"),
            user_id=uuid.uuid4(),
        )

    assert session.status == ExplorationStatus.CREATED.value
    assert enqueued["session_id"] == session.id
    assert enqueued["credential"] is None
    assert enqueued["selected_role"] is None
    assert enqueued["create_account"] is False


@pytest.mark.asyncio
async def test_submit_credentials_enqueues_with_credential(db_session):
    """submit_credentials should transition to AUTHENTICATING and enqueue with credential."""
    service = ExplorationService(db_session)

    user_id = uuid.uuid4()
    session = await service.repo.create(
        user_id=user_id,
        url="https://example.com/login",
        goal=None,
    )
    await db_session.commit()

    enqueued = {}

    async def mock_enqueue(session_id, credential=None, selected_role=None, create_account=False):
        enqueued["session_id"] = session_id
        enqueued["credential"] = credential
        enqueued["selected_role"] = selected_role
        enqueued["create_account"] = create_account

    with patch.object(ExplorationService, "_enqueue_exploration", side_effect=mock_enqueue):
        updated = await service.submit_credentials(
            session_id=session.id,
            user_id=user_id,
            data=ExplorationCredentialSubmit(
                email="user@example.com",
                password="secret123",
            ),
        )

    assert updated.status == ExplorationStatus.AUTHENTICATING.value
    assert enqueued["credential"] == {"email": "user@example.com", "password": "secret123"}
    assert enqueued["selected_role"] is None
    assert enqueued["create_account"] is False


@pytest.mark.asyncio
async def test_submit_answer_enqueues_with_role(db_session):
    """submit_answer should transition to DISCOVERING and enqueue with selected_role."""
    service = ExplorationService(db_session)

    user_id = uuid.uuid4()
    session = await service.repo.create(
        user_id=user_id,
        url="https://example.com",
        goal=None,
    )
    await db_session.commit()

    enqueued = {}

    async def mock_enqueue(session_id, credential=None, selected_role=None, create_account=False):
        enqueued["session_id"] = session_id
        enqueued["credential"] = credential
        enqueued["selected_role"] = selected_role
        enqueued["create_account"] = create_account

    with patch.object(ExplorationService, "_enqueue_exploration", side_effect=mock_enqueue):
        updated = await service.submit_answer(
            session_id=session.id,
            user_id=user_id,
            data=ExplorationAnswerSubmit(question_id="role-selection", answer="admin"),
        )

    assert updated.status == ExplorationStatus.DISCOVERING.value
    assert updated.selected_role == "admin"
    assert enqueued["selected_role"] == "admin"
    assert enqueued["credential"] is None


@pytest.mark.asyncio
async def test_create_account_enqueues_with_create_account_flag(db_session):
    """create_account should transition to AUTHENTICATING and enqueue with create_account=True."""
    service = ExplorationService(db_session)

    user_id = uuid.uuid4()
    session = await service.repo.create(
        user_id=user_id,
        url="https://example.com/signup",
        goal=None,
    )
    await db_session.commit()

    enqueued = {}

    async def mock_enqueue(session_id, credential=None, selected_role=None, create_account=False):
        enqueued["session_id"] = session_id
        enqueued["credential"] = credential
        enqueued["selected_role"] = selected_role
        enqueued["create_account"] = create_account

    with patch.object(ExplorationService, "_enqueue_exploration", side_effect=mock_enqueue):
        updated = await service.create_account(
            session_id=session.id,
            user_id=user_id,
            data=ExplorationCreateAccount(email="new@example.com", password="newpass123"),
        )

    assert updated.status == ExplorationStatus.AUTHENTICATING.value
    assert enqueued["credential"] == {"email": "new@example.com", "password": "newpass123"}
    assert enqueued["create_account"] is True


@pytest.mark.asyncio
async def test_cancel_session_requests_cancel_and_marks_cancelled(db_session):
    """cancel_session should request cancel via control channel and mark CANCELLED."""
    service = ExplorationService(db_session)

    user_id = uuid.uuid4()
    session = await service.repo.create(
        user_id=user_id,
        url="https://example.com",
        goal=None,
    )
    await db_session.commit()

    cancel_called = {}

    async def mock_request_cancel(session_id_str, reason=""):
        cancel_called["session_id"] = session_id_str
        cancel_called["reason"] = reason

    with patch(
        "app.modules.exploration.service.request_cancel", side_effect=mock_request_cancel
    ):
        result = await service.cancel_session(session_id=session.id, user_id=user_id)

    assert result.status == ExplorationStatus.CANCELLED.value
    assert cancel_called["session_id"] == str(session.id)
    assert "cancellation" in cancel_called["reason"].lower()
