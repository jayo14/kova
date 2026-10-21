"""Unit tests for secure session reuse, encryption, and race-safety (§Prompt C)."""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engine.browser.session import BrowserSession, SessionState
from app.modules.credentials.crypto import decrypt_credential
from app.modules.flows.auth.session_manager import SessionManager, extract_origin
from app.modules.product_graph.schemas import AuthCapability


@pytest.fixture
def session_manager():
    return SessionManager(redis_client=None)


def test_origin_extraction():
    assert extract_origin("https://app.example.com/login?next=/dash") == "https://app.example.com"
    assert extract_origin("http://127.0.0.1:8000/auth") == "http://127.0.0.1:8000"
    assert extract_origin("http://example.com:80/portal") == "http://example.com"
    assert extract_origin("https://example.com:443/portal") == "https://example.com"
    assert extract_origin("/relative") == "default"


@pytest.mark.asyncio
async def test_redis_and_store_never_contain_readable_cookie_values(session_manager):
    """Acceptance check: Redis / memory store never contains readable cookie values."""
    secret_token = "secret_session_jwt_super_sensitive_token_XYZ987"
    state = SessionState(
        cookies=[{"name": "auth_token", "value": secret_token, "domain": "example.com", "path": "/"}],
    )

    proj_id = str(uuid.uuid4())
    persona = "auditor"
    origin = "https://app.example.com"

    await session_manager.set(proj_id, persona, origin, state, execution_id="exec_1", ttl_seconds=60)

    # Inspect the raw stored representation
    key = session_manager._cache_key(proj_id, persona, origin)
    assert key in session_manager._memory_store

    raw_stored_ciphertext, expires_at = session_manager._memory_store[key]

    # Invariant 4: Never store plaintext cookies or tokens
    assert secret_token not in raw_stored_ciphertext
    assert "auth_token" not in raw_stored_ciphertext

    # Decrypting via master key retrieves the state
    decrypted_json = decrypt_credential(raw_stored_ciphertext)
    assert secret_token in decrypted_json

    # SessionManager.get returns the reconstructed SessionState
    retrieved = await session_manager.get(proj_id, persona, origin)
    assert retrieved is not None
    assert retrieved.cookies[0]["value"] == secret_token


@pytest.mark.asyncio
async def test_twenty_sequential_flows_perform_exactly_one_login(session_manager):
    """Acceptance check: 20 sequential flows for one persona perform exactly one login."""
    proj_id = uuid.uuid4()
    persona = "regular_user"
    cap = AuthCapability(project_id=proj_id, name="login", login_url="https://app.example.com/login", persona=persona)

    mock_browser = MagicMock()
    mock_browser.page = AsyncMock()
    mock_browser.restore_session_state = AsyncMock()

    # Authenticator spy
    auth_spy = MagicMock()
    login_count = 0

    async def mock_authenticate(*args, **kwargs):
        nonlocal login_count
        login_count += 1
        state = SessionState(cookies=[{"name": "sid", "value": f"tok_{login_count}"}])
        res = MagicMock()
        res.success = True
        res.session_state = state
        return res

    auth_spy.authenticate = AsyncMock(side_effect=mock_authenticate)

    # Mock verify_authenticated to return True for restored session
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.modules.flows.auth.session_manager.verify_authenticated",
            AsyncMock(return_value=(True, "SUCCESS")),
        )

        for i in range(20):
            exec_id = f"exec_{i + 1}"
            res = await session_manager.get_or_establish(
                execution_id=exec_id,
                persona=persona,
                capability=cap,
                browser=mock_browser,
                credential=MagicMock(),
                authenticator=auth_spy,
                target_url="https://app.example.com",
            )
            state, was_reused, reason = res
            assert state is not None
            if i == 0:
                assert was_reused is False
                assert "logged in fresh" in reason
            else:
                assert was_reused is True
                assert "session reused" in reason

    # Authenticate must have been called EXACTLY once across 20 executions!
    assert login_count == 1
    assert auth_spy.authenticate.call_count == 1


@pytest.mark.asyncio
async def test_expired_session_triggers_exactly_one_relogin(session_manager):
    """Acceptance check: An expired session triggers exactly one re-login."""
    proj_id = uuid.uuid4()
    persona = "expiring_user"
    cap = AuthCapability(project_id=proj_id, name="login", login_url="https://app.example.com/login", persona=persona)

    mock_browser = MagicMock()
    mock_browser.page = AsyncMock()
    mock_browser.restore_session_state = AsyncMock()

    login_count = 0

    async def mock_authenticate(*args, **kwargs):
        nonlocal login_count
        login_count += 1
        state = SessionState(cookies=[{"name": "sid", "value": f"tok_{login_count}"}])
        res = MagicMock()
        res.success = True
        res.session_state = state
        return res

    auth_spy = MagicMock()
    auth_spy.authenticate = AsyncMock(side_effect=mock_authenticate)

    # Initial login
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.modules.flows.auth.session_manager.verify_authenticated",
            AsyncMock(return_value=(True, "SUCCESS")),
        )
        res1 = await session_manager.get_or_establish(
            execution_id="exec_1",
            persona=persona,
            capability=cap,
            browser=mock_browser,
            credential=MagicMock(),
            authenticator=auth_spy,
            target_url="https://app.example.com",
        )
        assert res1[1] is False
        assert login_count == 1

    # Simulate server expiration: verify_authenticated returns False
    with pytest.MonkeyPatch.context() as mp:
        # First check fails (expired), post-login check succeeds
        verify_mock = AsyncMock(side_effect=[(False, "BAD_CREDENTIALS"), (True, "SUCCESS")])
        mp.setattr("app.modules.flows.auth.session_manager.verify_authenticated", verify_mock)

        res2 = await session_manager.get_or_establish(
            execution_id="exec_2",
            persona=persona,
            capability=cap,
            browser=mock_browser,
            credential=MagicMock(),
            authenticator=auth_spy,
            target_url="https://app.example.com",
        )
        # Must re-login
        assert res2[1] is False
        assert login_count == 2
        assert "cached session expired" in res2[2]

        # Subsequent execution reuses the new session
        mp.setattr(
            "app.modules.flows.auth.session_manager.verify_authenticated",
            AsyncMock(return_value=(True, "SUCCESS")),
        )
        res3 = await session_manager.get_or_establish(
            execution_id="exec_3",
            persona=persona,
            capability=cap,
            browser=mock_browser,
            credential=MagicMock(),
            authenticator=auth_spy,
            target_url="https://app.example.com",
        )
        assert res3[1] is True
        assert login_count == 2


@pytest.mark.asyncio
async def test_concurrent_executions_do_not_race_login(session_manager):
    """Verify concurrent calls serialize via lock and perform only one login."""
    proj_id = uuid.uuid4()
    persona = "racing_persona"
    cap = AuthCapability(project_id=proj_id, name="login", login_url="https://app.example.com/login", persona=persona)

    mock_browser = MagicMock()
    mock_browser.page = AsyncMock()
    mock_browser.restore_session_state = AsyncMock()

    login_count = 0

    async def mock_slow_authenticate(*args, **kwargs):
        nonlocal login_count
        login_count += 1
        await asyncio.sleep(0.05)
        state = SessionState(cookies=[{"name": "sid", "value": f"tok_{login_count}"}])
        res = MagicMock()
        res.success = True
        res.session_state = state
        return res

    auth_spy = MagicMock()
    auth_spy.authenticate = AsyncMock(side_effect=mock_slow_authenticate)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.modules.flows.auth.session_manager.verify_authenticated",
            AsyncMock(return_value=(True, "SUCCESS")),
        )

        tasks = [
            session_manager.get_or_establish(
                execution_id=f"concurrent_exec_{i}",
                persona=persona,
                capability=cap,
                browser=mock_browser,
                credential=MagicMock(),
                authenticator=auth_spy,
                target_url="https://app.example.com",
            )
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # All 5 succeed
        assert len(results) == 5
        # Only 1 performed fresh login
        fresh_logins = [r for r in results if r[1] is False]
        reused_sessions = [r for r in results if r[1] is True]

        assert len(fresh_logins) == 1
        assert len(reused_sessions) == 4
        assert login_count == 1


@pytest.mark.asyncio
async def test_wipe_clears_stored_sessions(session_manager):
    """Verify wipe clears cached sessions when a credential changes or is deleted."""
    proj_id = str(uuid.uuid4())
    state = SessionState(cookies=[{"name": "c", "value": "1"}])

    await session_manager.set(proj_id, "admin", "https://example.com", state)
    await session_manager.set(proj_id, "user", "https://example.com", state)

    assert await session_manager.get(proj_id, "admin", "https://example.com") is not None
    assert await session_manager.get(proj_id, "user", "https://example.com") is not None

    # Wipe only admin
    cleared = await session_manager.wipe(proj_id, persona="admin")
    assert cleared == 1
    assert await session_manager.get(proj_id, "admin", "https://example.com") is None
    assert await session_manager.get(proj_id, "user", "https://example.com") is not None

    # Wipe entire project
    await session_manager.wipe(proj_id)
    assert await session_manager.get(proj_id, "user", "https://example.com") is None
