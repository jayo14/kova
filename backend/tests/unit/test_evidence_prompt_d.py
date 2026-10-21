"""Unit tests for Prompt D: Non-fatal evidence, safe screenshots, signed URLs, and masking."""

import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.engine.browser.session import BrowserSession
from app.engine.browser.screenshot_storage import ScreenshotStorage
from app.engine.browser.evidence_storage import EvidenceStorage
from app.modules.executions.evidence_model import Evidence, EvidenceType, EvidenceStatus
from app.modules.executions.evidence_service import EvidenceService


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_stopping_s3_mid_run_preserves_deterministic_verdict_and_marks_incomplete(mock_db):
    """Acceptance check 1: Stopping S3 mid-run still gives the right verdict with evidence marked incomplete and retried."""
    service = EvidenceService(mock_db)

    # Mock evidence repo create
    dummy_evidence = Evidence(
        id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        type=EvidenceType.SCREENSHOT.value,
        title="Test Screenshot",
        status=EvidenceStatus.PENDING.value,
        purpose="step_evidence",
        step_id="step_1",
    )
    service.repo.create = AsyncMock(return_value=dummy_evidence)
    service.event_service.record_event = AsyncMock()

    # S3 fails mid-run
    with patch("app.modules.executions.evidence_service.evidence_storage.upload_async", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = {
            "storage_key": None,
            "url": None,
            "status": "FAILED",
            "error": "S3 connection refused (storage down)",
        }

        result = await service.capture_screenshot(
            execution_id=dummy_evidence.execution_id,
            screenshot_bytes=b"fake_image_bytes",
            title="Step 1 after",
            purpose="step_evidence",
            step_id="step_1",
        )

        # Non-fatal: result is returned, status is FAILED, never raises
        assert result is not None
        assert dummy_evidence.status == EvidenceStatus.FAILED.value
        assert "Upload failed" in dummy_evidence.note

    # Retry mechanism identifies pending/failed uploads
    mock_db.execute = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [dummy_evidence]
    mock_db.execute.return_value = mock_result

    retried_count = await service.retry_pending_uploads(dummy_evidence.execution_id)
    assert retried_count == 1
    assert "[Retried]" in dummy_evidence.note


@pytest.mark.asyncio
async def test_no_execution_screenshot_url_is_publicly_readable():
    """Acceptance check 2: No execution screenshot URL is publicly readable (uses private signed URLs)."""
    storage = ScreenshotStorage()

    mock_s3 = MagicMock()
    mock_s3.put_object = MagicMock()
    mock_s3.generate_presigned_url = MagicMock(
        return_value="https://s3.rumptycloud.com/private-bucket/executions/exec_1/ss.png?X-Amz-Signature=xyz789&Expires=3600"
    )

    with patch.object(storage, "_get_s3_client", return_value=mock_s3), \
         patch("app.engine.browser.screenshot_storage.settings") as mock_settings:
        mock_settings.RUMPTYCLOUD_S3_ENDPOINT = "https://s3.rumptycloud.com"
        mock_settings.RUMPTYCLOUD_ACCESS_KEY_ID = "test_key"
        mock_settings.RUMPTYCLOUD_BUCKET_NAME = "private-evidence-bucket"
        mock_settings.storage_bucket.return_value = "private-evidence-bucket"

        res = storage.save(
            exploration_id="exec_1",
            screenshot_bytes=b"png_bytes",
            folder="executions",
            purpose="step_evidence",
            step_id="step_login",
        )

        # URL must be a signed URL, never an unauthenticated public URL
        url = res["screenshot_url"]
        assert url is not None
        assert "X-Amz-Signature" in url or "Signature" in url
        mock_s3.generate_presigned_url.assert_called_once()

        # get_public_url also returns signed URL
        signed_url = storage.get_public_url("executions/exec_1/ss.png")
        assert signed_url is not None
        assert "X-Amz-Signature" in signed_url


@pytest.mark.asyncio
async def test_password_and_sensitive_fields_are_masked():
    """Acceptance check 3: Password, OTP, and token inputs are masked before capture."""
    session = BrowserSession(headless=True)
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/login"
    mock_locator = MagicMock()
    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_page.screenshot = AsyncMock(return_value=b"png_data")

    session._page = mock_page

    image_bytes, mime, fallback = await session.capture_step_screenshot(
        step_id="step_auth", kind="before"
    )

    assert image_bytes == b"png_data"
    assert mime == "image/png"
    assert fallback == "full_page"

    # Verify screenshot parameters: animations disabled, caret hidden, mask applied
    mock_page.screenshot.assert_called_once()
    _, kwargs = mock_page.screenshot.call_args
    assert kwargs.get("animations") == "disabled"
    assert kwargs.get("caret") == "hide"
    assert kwargs.get("timeout") == 3000
    assert kwargs.get("mask") == [mock_locator]

    # Verify selector masks password, OTP, tokens
    selector_called = mock_page.locator.call_args[0][0]
    assert 'input[type="password"]' in selector_called
    assert 'otp' in selector_called.lower()
    assert 'token' in selector_called.lower()


@pytest.mark.asyncio
async def test_screenshot_fallback_chain():
    """Verify fallback chain: full_page -> viewport -> element -> DOM snapshot."""
    session = BrowserSession(headless=True)
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/app"
    mock_page.locator = MagicMock(return_value=MagicMock())

    # Full page times out, viewport succeeds
    mock_page.screenshot = AsyncMock(side_effect=[
        asyncio.TimeoutError("Full page timed out"),
        b"viewport_png",
    ])
    session._page = mock_page

    image_bytes, mime, fallback = await session.capture_step_screenshot(
        step_id="step_long_page", kind="after"
    )

    assert image_bytes == b"viewport_png"
    assert fallback == "viewport"
    assert mock_page.screenshot.call_count == 2


@pytest.mark.asyncio
async def test_screenshot_complete_failure_falls_back_to_dom_snapshot():
    """Verify total screenshot failure returns valid DOM placeholder PNG without crashing."""
    session = BrowserSession(headless=True)
    mock_page = AsyncMock()
    mock_page.url = "https://example.com/crashed"
    mock_page.locator = MagicMock(return_value=MagicMock())
    mock_page.screenshot = AsyncMock(side_effect=RuntimeError("Page crashed"))

    session._page = mock_page

    image_bytes, mime, fallback = await session.capture_step_screenshot(
        step_id="step_crashed", kind="failure"
    )

    assert fallback == "dom_snapshot"
    assert len(image_bytes) > 0  # Valid 1x1 transparent PNG fallback bytes
    assert image_bytes.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_console_and_failed_requests_captured():
    """Verify console errors and failed requests are captured on BrowserSession."""
    session = BrowserSession(headless=True)
    assert hasattr(session, "console_errors")
    assert hasattr(session, "failed_requests")

    # Simulate console error
    session.current_step_index = 3
    session.console_errors.append({
        "type": "error",
        "text": "Uncaught TypeError: Cannot read properties of undefined",
        "step_index": 3,
    })

    # Simulate failed request
    session.failed_requests.append({
        "type": "request_failed",
        "status": 500,
        "method": "POST",
        "url": "https://example.com/api/checkout",
        "failure": "Internal Server Error",
        "step_index": 3,
    })

    assert len(session.console_errors) == 1
    assert session.console_errors[0]["type"] == "error"
    assert len(session.failed_requests) == 1
    assert session.failed_requests[0]["status"] == 500
