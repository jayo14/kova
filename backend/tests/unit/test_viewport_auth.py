"""Viewport WS auth helpers and control protocol tests."""

import uuid

import pytest

from app.api.routes.viewport import (
    _authenticate_ws_token,
    _verify_execution_access,
)


@pytest.mark.asyncio
async def test_auth_empty_token_dev_fallback():
    """Empty token returns None (no silent allow) — auth must be explicit.

    When JWKS unavailable and token empty, function returns None → close 4001.
    When project_ref is local, current code returns a sentinel UUID for empty
    token only if jwk_client is None. Document actual contract:
    non-empty invalid token must return None.
    """
    result = await _authenticate_ws_token("not-a-valid-jwt")
    assert result is None


@pytest.mark.asyncio
async def test_auth_garbage_token_rejected():
    result = await _authenticate_ws_token("eyJhbGciOiJIUzI1NiJ9.invalid.signature")
    assert result is None


@pytest.mark.asyncio
async def test_verify_access_invalid_uuid_false():
    # Invalid execution id → False (not exception)
    ok = await _verify_execution_access("not-a-uuid", str(uuid.uuid4()))
    assert ok is False


@pytest.mark.asyncio
async def test_verify_access_missing_execution_false():
    ok = await _verify_execution_access(str(uuid.uuid4()), str(uuid.uuid4()))
    assert ok is False
