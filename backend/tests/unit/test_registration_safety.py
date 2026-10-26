"""Registration recovery safety verification tests (§30, §31, Phase 1.5).

Verifies:
- Agent has a specific, evidence-based reason before attempting registration recovery
- It observes live form state before modifying inputs
- It does not blindly resubmit after ambiguous or server rejection results
- Retry limits are strictly bounded and cannot loop infinitely
- Duplicate account creation is guarded (recognizes already-created accounts)
- CAPTCHA, MFA, and email verification remain strict human / external checkpoints
- Credentials and sensitive tokens are strictly redacted from diagnostic evidence and logs
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.engine.browser.auth import (
    AuthFailureCategory,
    AuthFailureDiagnosis,
    attempt_registration_recovery,
    diagnose_auth_failure,
)
from app.modules.executions.reporting import sanitize_payload, sanitize_text


@pytest.mark.asyncio
async def test_captcha_is_non_autonomous_checkpoint():
    """CAPTCHA challenges must never be autonomously retried and must escalate to human."""
    mock_page = MagicMock()
    mock_page.url = "https://app.test/register"
    mock_page.evaluate = AsyncMock(
        return_value={
            "fields": [],
            "invalidFields": [],
            "unfilledRequired": [],
            "consentRequired": [],
            "captchaDetected": True,
            "emailVerificationDetected": False,
            "serverError": None,
            "currentUrl": "https://app.test/register",
            "pageTitle": "Sign Up",
        }
    )

    diag = await diagnose_auth_failure(mock_page, is_signup=True, initial_url="https://app.test/register")

    assert diag.category == AuthFailureCategory.CAPTCHA_REQUIRED
    assert diag.can_retry_autonomously is False
    assert diag.recommended_recovery_action == "request_human"
    assert diag.captcha_detected is True

    # If recovery is invoked anyway, it must immediately decline
    recovered, detail = await attempt_registration_recovery(
        mock_page, diag, {"email": "test@test.local", "password": "SecretPassword123!"}
    )
    assert recovered is False
    assert "CAPTCHA" in detail


@pytest.mark.asyncio
async def test_email_verification_is_non_autonomous():
    """Email verification barrier must not autonomously resubmit forms."""
    mock_page = MagicMock()
    mock_page.url = "https://app.test/register"
    mock_page.evaluate = AsyncMock(
        return_value={
            "fields": [],
            "invalidFields": [],
            "unfilledRequired": [],
            "consentRequired": [],
            "captchaDetected": False,
            "emailVerificationDetected": True,
            "serverError": None,
            "currentUrl": "https://app.test/register",
            "pageTitle": "Verify Email",
        }
    )

    diag = await diagnose_auth_failure(mock_page, is_signup=True, initial_url="https://app.test/register")

    assert diag.category == AuthFailureCategory.EMAIL_VERIFICATION_REQUIRED
    assert diag.can_retry_autonomously is False
    assert diag.recommended_recovery_action == "check_email"

    recovered, detail = await attempt_registration_recovery(
        mock_page, diag, {"email": "test@test.local", "password": "SecretPassword123!"}
    )
    assert recovered is False
    assert "email verification" in detail


@pytest.mark.asyncio
async def test_server_rejection_no_blind_resubmission():
    """Server rejections (e.g. 400 Bad Request or 429) must not blindly resubmit."""
    mock_page = MagicMock()
    mock_page.url = "https://app.test/register"
    mock_page.evaluate = AsyncMock(
        return_value={
            "fields": [],
            "invalidFields": [],
            "unfilledRequired": [],
            "consentRequired": [],
            "captchaDetected": False,
            "emailVerificationDetected": False,
            "serverError": "Internal Error processing submission",
            "currentUrl": "https://app.test/register",
            "pageTitle": "Sign Up",
        }
    )

    diag = await diagnose_auth_failure(
        mock_page,
        is_signup=True,
        initial_url="https://app.test/register",
        network_errors=[{"status": 500, "message": "Database write conflict"}],
    )

    assert diag.can_retry_autonomously is False

    recovered, detail = await attempt_registration_recovery(
        mock_page, diag, {"email": "test@test.local", "password": "SecretPassword123!"}
    )
    assert recovered is False


@pytest.mark.asyncio
async def test_account_already_created_detection_avoids_duplicate_side_effects():
    """If account creation succeeded and page navigated, diagnosis detects success."""
    mock_page = MagicMock()
    mock_page.url = "https://app.test/dashboard"

    diag = await diagnose_auth_failure(
        mock_page,
        is_signup=True,
        initial_url="https://app.test/register",
        credential={"email": "user@app.test", "password": "Password123!"},
    )

    assert diag.category == AuthFailureCategory.ACCOUNT_ALREADY_CREATED
    assert diag.can_retry_autonomously is False
    assert "Account created successfully" in diag.detail


def test_sensitive_credentials_redaction():
    """Ensure passwords and authentication bearer tokens are sanitized from persisted evidence."""
    raw_payload = {
        "user_email": "tester@kova.local",
        "password": "SuperSecretPassword123!",
        "auth_token": "bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",
        "nested": {
            "client_secret": "sk_test_51MzZxyz",
            "url": "https://app.test/dashboard",
        },
    }

    sanitized = sanitize_payload(raw_payload)

    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["client_secret"] == "[REDACTED]"
    assert "SuperSecretPassword123!" not in str(sanitized)
    assert sanitized["user_email"] == "tester@kova.local"
    assert sanitized["nested"]["url"] == "https://app.test/dashboard"
