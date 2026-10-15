import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.browser.session import SessionState
from app.modules.flows.auth import Authenticator, SessionManager
from app.modules.product_graph.schemas import AuthCapability


@pytest.mark.asyncio
async def test_session_manager_ttl_expiration():
    sm = SessionManager()
    exec_id = str(uuid.uuid4())
    state = SessionState(
        cookies=[{"name": "session_id", "value": "12345", "domain": "example.com"}],
        local_storage={"token": "jwt_token"},
    )

    # Set with 1-second TTL
    await sm.set(exec_id, "student", state, ttl_seconds=1)

    # Immediate retrieval succeeds
    cached = await sm.get(exec_id, "student")
    assert cached is not None
    assert cached.cookies[0]["value"] == "12345"

    # Wait for TTL expiration
    await asyncio.sleep(1.1)
    expired = await sm.get(exec_id, "student")
    assert expired is None


@pytest.mark.asyncio
async def test_session_manager_persona_isolation():
    sm = SessionManager()
    exec_id = str(uuid.uuid4())

    student_state = SessionState(cookies=[{"name": "role", "value": "student"}])
    admin_state = SessionState(cookies=[{"name": "role", "value": "admin"}])

    await sm.set(exec_id, "student", student_state, ttl_seconds=300)
    await sm.set(exec_id, "admin", admin_state, ttl_seconds=300)

    got_student = await sm.get(exec_id, "student")
    got_admin = await sm.get(exec_id, "admin")
    got_other = await sm.get(exec_id, "guest")

    assert got_student.cookies[0]["value"] == "student"
    assert got_admin.cookies[0]["value"] == "admin"
    assert got_other is None


@pytest.mark.asyncio
async def test_session_manager_restoration_idempotence():
    sm = SessionManager()
    exec_id = str(uuid.uuid4())

    state = SessionState(
        cookies=[{"name": "auth_cookie", "value": "secret"}],
        local_storage={"theme": "dark", "user_id": "u-42"},
        session_storage={"tab": "home"},
    )

    mock_browser = MagicMock()
    mock_browser.restore_session_state = AsyncMock()

    mock_authenticator = MagicMock()
    mock_authenticator.authenticate = AsyncMock()

    cap = AuthCapability(
        project_id=uuid.uuid4(),
        name="auth_student",
        persona="student",
    )

    # 1. First call: not cached, authenticator runs
    from app.modules.flows.auth.strategies.base import AuthResult
    mock_authenticator.authenticate.return_value = AuthResult(
        success=True,
        session_state=state,
    )

    res_state, was_reused = await sm.get_or_establish(
        execution_id=exec_id,
        persona="student",
        capability=cap,
        browser=mock_browser,
        credential=MagicMock(),
        authenticator=mock_authenticator,
    )

    assert was_reused is False
    assert res_state == state
    assert mock_authenticator.authenticate.call_count == 1

    # 2. Second call in same execution: cached, authenticator NOT called again
    res_state_2, was_reused_2 = await sm.get_or_establish(
        execution_id=exec_id,
        persona="student",
        capability=cap,
        browser=mock_browser,
        credential=MagicMock(),
        authenticator=mock_authenticator,
    )

    assert was_reused_2 is True
    assert res_state_2.cookies[0]["value"] == "secret"
    # Authenticator was NOT called a second time!
    assert mock_authenticator.authenticate.call_count == 1
    # Browser restore was called
    mock_browser.restore_session_state.assert_called_with(state)


@pytest.mark.asyncio
async def test_session_manager_clear():
    sm = SessionManager()
    exec_id = str(uuid.uuid4())

    state = SessionState(cookies=[{"name": "token", "value": "abc"}])
    await sm.set(exec_id, "student", state, ttl_seconds=300)

    assert await sm.get(exec_id, "student") is not None
    await sm.clear(exec_id, "student")
    assert await sm.get(exec_id, "student") is None
