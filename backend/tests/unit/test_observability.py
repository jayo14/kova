"""Unit tests for Observability, Structured Logging, Metrics, and Tracing."""

import json
import logging
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.config.settings import settings
from app.main import app
from app.observability.logging import (
    KovaJsonFormatter,
    configure_logging,
    request_id_ctx,
    set_current_request_id,
)
from app.observability.metrics import (
    HTTP_REQUESTS_TOTAL,
    record_browser_crash,
    record_evidence_upload_failure,
    record_execution_completed,
    record_execution_started,
)
from app.observability.redaction import redact, REDACTED_STR


def test_redaction_filter_redacts_known_keys():
    """redact({"password": "abc", "name": "John"}) returns redacted password."""
    payload = {"password": "abc", "name": "John"}
    scrubbed = redact(payload)
    assert scrubbed["password"] == REDACTED_STR
    assert scrubbed["name"] == "John"


def test_redaction_filter_recursive():
    """Nested dicts, lists, and sensitive strings inside arrays are scrubbed recursively."""
    payload = {
        "user": {
            "name": "Alice",
            "api_key": "super-secret-key-123",
            "tokens": ["normal", "kova_0123456789abcdef0123456789abcdef"],
        },
        "items": [
            {"webhook_secret": "whsec_xyz"},
            {"cookie": "session=abc"},
        ],
        "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz",
    }
    scrubbed = redact(payload)
    assert scrubbed["user"]["api_key"] == REDACTED_STR
    assert scrubbed["user"]["tokens"][0] == "normal"
    assert scrubbed["user"]["tokens"][1] == REDACTED_STR
    assert scrubbed["items"][0]["webhook_secret"] == REDACTED_STR
    assert scrubbed["items"][1]["cookie"] == REDACTED_STR
    assert REDACTED_STR in scrubbed["auth_header"]
    assert "Alice" in scrubbed["user"]["name"]


def test_structured_logger_emits_json():
    """With JsonFormatter, log records emit valid JSON with required fields."""
    formatter = KovaJsonFormatter(
        "%(timestamp)s %(level)s %(logger)s %(message)s %(request_id)s %(trace_id)s"
    )

    test_req_id = str(uuid.uuid4())
    set_current_request_id(test_req_id)

    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=42,
        msg="Processing execution with password: %s",
        args=("SecretPassword99!",),
        exc_info=None,
    )
    record.request_id = test_req_id

    formatted_str = formatter.format(record)
    parsed = json.loads(formatted_str)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert "timestamp" in parsed
    assert parsed["request_id"] == test_req_id
    assert "trace_id" in parsed
    # Secret should be redacted
    assert "SecretPassword99!" not in parsed["message"]
    assert REDACTED_STR in parsed["message"]


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format():
    """GET /metrics returns text in Prometheus format and includes key metrics."""
    # Pre-record a sample metric
    record_execution_started("test-org-1", plan="free", trigger="manual")
    record_execution_completed("test-org-1", plan="free", status="completed", duration_seconds=1.23)
    record_browser_crash("test-org-1")
    record_evidence_upload_failure("network_timeout")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        text = resp.text
        assert "http_requests_total" in text
        assert "executions_started_total" in text
        assert "executions_completed_total" in text
        assert "browser_crashes_total" in text
        assert "evidence_upload_failures_total" in text


@pytest.mark.asyncio
async def test_metrics_endpoint_ip_restricted(monkeypatch):
    """In production, requests from non-allowed IPs return 403."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "PROMETHEUS_ALLOWED_IPS", "192.168.1.100")

    transport = ASGITransport(app=app, client=("10.0.0.1", 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Request from non-allowed client IP 10.0.0.1
        resp = await c.get("/metrics")
        assert resp.status_code == 403
        assert "restricted" in resp.json()["detail"].lower()

    # Allowed IP request succeeds
    transport_allowed = ASGITransport(app=app, client=("192.168.1.100", 12345))
    async with AsyncClient(transport=transport_allowed, base_url="http://test") as c:
        resp = await c.get("/metrics")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_tracing_propagates_request_id():
    """An HTTP request returns X-Request-Id header and logs correlate with that ID."""
    custom_id = f"test-trace-{uuid.uuid4().hex[:8]}"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 1. With provided header
        resp = await c.get("/health", headers={"X-Request-Id": custom_id})
        assert resp.status_code == 200
        assert resp.headers["X-Request-Id"] == custom_id

        # 2. Without header, server generates UUID
        resp2 = await c.get("/health")
        assert resp2.status_code == 200
        assert "X-Request-Id" in resp2.headers
        generated_id = resp2.headers["X-Request-Id"]
        # Validate valid UUID
        assert uuid.UUID(generated_id)
