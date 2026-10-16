"""Structured JSON logger with sensitive data scrubbing and correlation IDs."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import logging
import sys
import uuid
from typing import Any, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from pythonjsonlogger import jsonlogger

from app.config.settings import settings
from app.observability.redaction import RedactionFilter, redact

# Context variables for distributed tracing & log correlation
request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
org_id_ctx: ContextVar[Optional[str]] = ContextVar("org_id", default=None)
project_id_ctx: ContextVar[Optional[str]] = ContextVar("project_id", default=None)
execution_id_ctx: ContextVar[Optional[str]] = ContextVar("execution_id", default=None)


def get_current_request_id() -> Optional[str]:
    return request_id_ctx.get()


def set_current_request_id(req_id: str) -> None:
    request_id_ctx.set(req_id)


def set_correlation_context(
    *,
    request_id: Optional[str] = None,
    org_id: Optional[str] = None,
    project_id: Optional[str] = None,
    execution_id: Optional[str] = None,
) -> None:
    if request_id is not None:
        request_id_ctx.set(request_id)
    if org_id is not None:
        org_id_ctx.set(org_id)
    if project_id is not None:
        project_id_ctx.set(project_id)
    if execution_id is not None:
        execution_id_ctx.set(execution_id)


class KovaJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with standard fields, correlation IDs, and secret redaction."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        # Standard observability keys
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name

        if record.args:
            record.args = redact(record.args)
        log_record["message"] = redact(record.getMessage())

        # Correlation IDs from context or record
        req_id = getattr(record, "request_id", None) or request_id_ctx.get()
        log_record["request_id"] = req_id or ""

        org_id = getattr(record, "org_id", None) or org_id_ctx.get()
        log_record["org_id"] = org_id or ""

        proj_id = getattr(record, "project_id", None) or project_id_ctx.get()
        log_record["project_id"] = proj_id or ""

        exec_id = getattr(record, "execution_id", None) or execution_id_ctx.get()
        log_record["execution_id"] = exec_id or ""

        # OpenTelemetry Trace IDs if available
        try:
            from opentelemetry import trace
            span = trace.get_current_span()
            ctx = span.get_span_context() if span else None
            if ctx and ctx.is_valid:
                log_record["trace_id"] = f"{ctx.trace_id:032x}"
                log_record["span_id"] = f"{ctx.span_id:016x}"
            else:
                log_record["trace_id"] = ""
                log_record["span_id"] = ""
        except Exception:
            log_record["trace_id"] = ""
            log_record["span_id"] = ""

        # Extra metadata
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_record["extra"] = redact(record.extra)

        # Scrub log_record before formatting
        for k in list(log_record.keys()):
            log_record[k] = redact(log_record[k])


def configure_logging(log_format: Optional[str] = None) -> None:
    """Configure root logger with either JSON or text format and redaction filters."""
    fmt_mode = (log_format or settings.LOG_FORMAT).lower()
    root_logger = logging.getLogger()
    log_level = logging.DEBUG if settings.effective_debug else logging.INFO
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.addFilter(RedactionFilter())

    if fmt_mode == "json":
        formatter = KovaJsonFormatter(
            "%(timestamp)s %(level)s %(logger)s %(message)s %(request_id)s %(org_id)s %(project_id)s %(execution_id)s %(trace_id)s %(span_id)s"
        )
    else:
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware attaching request_id to context and response headers."""

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        set_current_request_id(req_id)

        response: Response = await call_next(request)
        response.headers["X-Request-Id"] = req_id
        return response
