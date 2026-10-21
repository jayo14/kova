"""Unit tests for truth-telling authentication verification and strategies (§Prompt B)."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.modules.flows.auth.verifier import AuthReasonCode, verify_authenticated
from app.modules.flows.auth.strategies.base import AuthResult
from app.modules.flows.auth.strategies.password_form import PasswordFormStrategy
from app.modules.flows.auth.strategies.otp import OTPStrategy
from app.modules.flows.auth.strategies.oauth import OAuthStrategy
from app.modules.flows.auth.strategies.magic_link import MagicLinkStrategy
from app.modules.product_graph.schemas import AuthCapability


@pytest.mark.asyncio
async def test_verify_authenticated_all_reason_codes():
    """Verify that verify_authenticated accurately classifies each reason code."""
    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_browser.page = mock_page
    mock_browser.context.cookies = AsyncMock(return_value=[])

    # 1. BAD_CREDENTIALS
    mock_page.url = "http://localhost:8000/login"
    mock_page.inner_text.return_value = "Invalid username or password. Please try again."
    pwd_el = AsyncMock()
    pwd_el.is_visible.return_value = True
    mock_page.query_selector.side_effect = lambda sel: pwd_el if "password" in sel else None
    mock_page.locator.return_value.count = AsyncMock(return_value=0)

    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is False
    assert reason == AuthReasonCode.BAD_CREDENTIALS

    # 2. NEEDS_OTP
    mock_page.inner_text.return_value = "Please enter the 6-digit authenticator code to proceed."
    mock_page.query_selector.side_effect = lambda sel: AsyncMock() if "otp" in sel or "code" in sel else None
    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is False
    assert reason == AuthReasonCode.NEEDS_OTP

    # 3. NEEDS_CAPTCHA
    mock_page.inner_text.return_value = "Security check: Please verify that you are human (Turnstile challenge)."
    mock_page.query_selector.side_effect = lambda sel: None
    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is False
    assert reason == AuthReasonCode.NEEDS_CAPTCHA

    # 4. NEEDS_EMAIL_VERIFICATION
    mock_page.inner_text.return_value = "Check your inbox: We sent an activation link to your email."
    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is False
    assert reason == AuthReasonCode.NEEDS_EMAIL_VERIFICATION

    # 5. SSO_ONLY
    mock_page.inner_text.return_value = "Organization requires SSO. Please log in with your company account."
    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is False
    assert reason == AuthReasonCode.SSO_ONLY

    # 6. SITE_ERROR
    mock_page.inner_text.return_value = "500 Internal Server Error. Something went wrong on our end."
    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is False
    assert reason == AuthReasonCode.SITE_ERROR

    # 7. SUCCESS
    mock_page.url = "http://localhost:8000/dashboard"
    mock_page.inner_text.return_value = "Welcome back, alice! Log Out | Settings"
    mock_page.query_selector.side_effect = lambda sel: None
    mock_browser.context.cookies.return_value = [{"name": "session_id", "value": "s_123"}]

    is_authed, reason = await verify_authenticated(mock_browser)
    assert is_authed is True
    assert reason == AuthReasonCode.SUCCESS


@pytest.mark.asyncio
async def test_wrong_otp_never_yields_success():
    """Verify OTP strategy fails closed and never falls back to 123456 without secret."""
    strategy = OTPStrategy()
    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_browser.page = mock_page
    mock_page.url = "http://localhost:8000/login"

    # Credential with no TOTP secret and no email
    cred = MagicMock(spec=[])  # Empty credential object

    cap = AuthCapability(project_id=uuid.uuid4(), name="test_otp", login_url="/login")
    result = await strategy.execute(capability=cap, browser=mock_browser, credential=cred)

    assert result.success is False
    assert result.reason_code == AuthReasonCode.NEEDS_OTP
    assert result.failure_category == "AUTH"
    assert "no code available" in result.failure_reason


@pytest.mark.asyncio
async def test_oauth_strategy_returns_sso_only_without_storage_state():
    """Verify OAuth strategy returns SSO_ONLY instructions when no storage_state is uploaded."""
    strategy = OAuthStrategy()
    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_browser.page = mock_page
    mock_browser.context = AsyncMock()

    cred = MagicMock(spec=[])  # No storage_state
    cap = AuthCapability(project_id=uuid.uuid4(), name="test_oauth", login_url="/oauth/login", persona="admin")

    result = await strategy.execute(capability=cap, browser=mock_browser, credential=cred)

    assert result.success is False
    assert result.reason_code == AuthReasonCode.SSO_ONLY
    assert result.failure_category == "AUTH"
    assert "SSO_ONLY" in result.failure_reason
    assert "storage_state" in result.failure_reason


@pytest.mark.asyncio
async def test_oauth_strategy_succeeds_with_valid_storage_state():
    """Verify OAuth strategy applies uploaded storage_state and verifies session."""
    strategy = OAuthStrategy()
    mock_browser = MagicMock()
    mock_page = AsyncMock()
    mock_browser.page = mock_page
    mock_browser.context = AsyncMock()
    mock_browser.navigate = AsyncMock()
    mock_browser.save_session_state = AsyncMock(return_value={"state": "valid"})

    # Setup page state post-restore
    mock_page.url = "http://localhost:8000/dashboard"
    mock_page.inner_text.return_value = "Dashboard Welcome"
    mock_page.query_selector.side_effect = lambda sel: None
    mock_browser.context.cookies.return_value = [{"name": "auth_token", "value": "oauth_tok"}]

    cred = MagicMock()
    cred.storage_state = {"cookies": [{"name": "auth_token", "value": "oauth_tok", "domain": "localhost", "path": "/"}]}
    cap = AuthCapability(project_id=uuid.uuid4(), name="test_oauth", login_url="/dashboard", persona="admin")

    result = await strategy.execute(capability=cap, browser=mock_browser, credential=cred)

    assert result.success is True
    assert result.reason_code == AuthReasonCode.SUCCESS
    assert result.session_state is not None
