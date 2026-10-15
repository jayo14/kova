import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.browser.session import SessionState
from app.modules.flows.auth.strategies.password_form import PasswordFormStrategy
from app.modules.product_graph.schemas import AuthCapability


@pytest.mark.asyncio
async def test_auth_evidence_generation():
    """Assert every authentication attempt produces >= 3 evidence rows with purpose='auth_attempt'."""
    strategy = PasswordFormStrategy()

    cap = AuthCapability(
        project_id=uuid.uuid4(),
        name="user_login",
        login_url="http://127.0.0.1:8000/login",
        success_url_pattern=r"/dashboard",
    )

    mock_browser = MagicMock()
    mock_browser.page = MagicMock()
    mock_browser.page.url = "http://127.0.0.1:8000/login"
    mock_browser.navigate = AsyncMock()
    mock_browser.fill = AsyncMock()
    mock_browser.click = AsyncMock()
    mock_browser.screenshot = AsyncMock(return_value=b"fake_png_data")
    mock_browser.save_session_state = AsyncMock(return_value=SessionState(cookies=[{"name": "auth", "value": "xyz"}]))

    # Mock inputs
    mock_input = MagicMock()
    mock_input.is_visible = AsyncMock(return_value=True)
    mock_browser.page.query_selector = AsyncMock(return_value=mock_input)

    # After submit, page URL transitions to dashboard
    async def mock_submit_effect(*args, **kwargs):
        mock_browser.page.url = "http://127.0.0.1:8000/dashboard"

    mock_browser.click.side_effect = mock_submit_effect

    mock_cred = MagicMock()
    mock_cred.email = "student@example.com"
    mock_cred.password = "TopSecret123!"

    result = await strategy.execute(
        capability=cap,
        browser=mock_browser,
        credential=mock_cred,
        execution_id="exec-123",
    )

    assert result.success is True
    assert len(result.evidence) >= 3

    # Check evidence fields
    pre_submit = next((e for e in result.evidence if e.get("metadata", {}).get("phase") == "pre_submit"), None)
    post_submit = next((e for e in result.evidence if e.get("metadata", {}).get("phase") == "post_submit"), None)
    net_log = next((e for e in result.evidence if e.get("type") == "network_log"), None)

    assert pre_submit is not None
    assert pre_submit["purpose"] == "auth_attempt"
    assert "auth:user_login:attempt_1" in pre_submit["step_id"]

    assert post_submit is not None
    assert post_submit["purpose"] == "auth_attempt"
    assert "auth:user_login:attempt_1" in post_submit["step_id"]

    assert net_log is not None
    assert net_log["purpose"] == "auth_attempt"
    assert "auth:user_login:attempt_1" in net_log["step_id"]

    # Assert password and sensitive cookies are never logged
    assert net_log["metadata"]["password_redacted"] is True
    assert "TopSecret123!" not in str(net_log)
