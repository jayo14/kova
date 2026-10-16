"""Smoke test: Production security invariants and AUDIT.md controls."""

import uuid
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.config.settings import Settings, settings
from app.engine.verification.verifier import is_vacuous_condition
from app.engine.browser.session import _is_safe_url
from app.main import app
from app.modules.auth.dependencies import get_current_user
from app.observability.redaction import redact, REDACTED_STR


def test_production_jwt_secret_validation():
    """In production, JWT_SECRET_KEY must be >= 32 characters or raise ValueError."""
    with pytest.raises(ValueError, match="must be at least 32 characters long"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="too-short",
        )


@pytest.mark.asyncio
async def test_production_dev_user_fallback_disabled():
    """In production, requests without Authorization header must be rejected with 401."""
    with patch.object(settings, "ENVIRONMENT", "production"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/auth/me")
            assert res.status_code == 401


def test_ssrf_blocks_private_and_metadata_ips():
    """SSRF filter rejects loopback, private ranges, and AWS/GCP metadata IP 169.254.169.254."""
    blocked_urls = [
        "http://127.0.0.1:8000/api",
        "http://localhost:3000",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/router",
    ]
    for url in blocked_urls:
        assert _is_safe_url(url, allow_loopback=False) is False

    assert _is_safe_url("https://example.com") is True
    assert _is_safe_url("https://github.com/login") is True


def test_redaction_filter_sanitizes_sensitive_data():
    """Redaction filter scrubs passwords, tokens, API keys, cookies, and bearer tokens."""
    sensitive_dict = {
        "email": "user@example.com",
        "password": "SuperSecretPassword123!",
        "api_key": "kova_tok_1234567890abcdef",
        "cookie": "session_id=abcdef123456",
        "auth": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    }
    scrubbed = redact(sensitive_dict)
    assert scrubbed["email"] == "user@example.com"
    assert scrubbed["password"] == REDACTED_STR
    assert scrubbed["api_key"] == REDACTED_STR
    assert scrubbed["cookie"] == REDACTED_STR
    assert REDACTED_STR in scrubbed["auth"]


def test_vacuous_expectation_rejection():
    """Assertions with vacuous wildcards or empty conditions are rejected."""
    assert is_vacuous_condition({}) is True
    assert is_vacuous_condition({"url_matches": ".*"}) is True
    assert is_vacuous_condition({"element_visible": {"css": "main"}}) is True
    assert is_vacuous_condition({"text_visible": "Dashboard"}) is False
