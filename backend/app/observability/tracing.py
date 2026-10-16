"""OpenTelemetry distributed tracing configuration, context propagation, and middleware."""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import logging
from typing import Any, AsyncGenerator, Generator, Optional

from fastapi import Request, Response
from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Status, StatusCode
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.settings import settings
from app.observability.logging import (
    get_current_request_id,
    request_id_ctx,
    org_id_ctx,
    project_id_ctx,
    execution_id_ctx,
)

logger = logging.getLogger(__name__)
_tracer_initialized = False


def configure_tracing() -> None:
    """Initialize OpenTelemetry tracer provider with OTLP exporter if configured."""
    global _tracer_initialized
    if _tracer_initialized:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: "kova-backend",
            "environment": settings.ENVIRONMENT,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            otlp_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info("OpenTelemetry configured with OTLP endpoint: %s", settings.OTEL_EXPORTER_OTLP_ENDPOINT)
        except Exception as e:
            logger.warning("Failed to configure OTLP exporter: %s", e)

    trace.set_tracer_provider(provider)
    _tracer_initialized = True


def get_tracer(name: str = "kova") -> trace.Tracer:
    """Get named tracer instance."""
    return trace.get_tracer(name)


@contextmanager
def trace_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Generator[trace.Span, None, None]:
    """Synchronous context manager for creating child spans."""
    tracer = get_tracer("kova.runner")
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    span.set_attribute(str(k), str(v))
        yield span


@asynccontextmanager
async def async_trace_span(name: str, attributes: Optional[dict[str, Any]] = None) -> AsyncGenerator[trace.Span, None]:
    """Asynchronous context manager for creating child spans."""
    tracer = get_tracer("kova.runner")
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    span.set_attribute(str(k), str(v))
        yield span


class FastAPITracingMiddleware(BaseHTTPMiddleware):
    """Starts a distributed tracing span for incoming HTTP requests."""

    async def dispatch(self, request: Request, call_next):
        tracer = get_tracer("kova.http")
        span_name = f"HTTP {request.method} {request.url.path}"

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            req_id = get_current_request_id() or request.headers.get("x-request-id", "")
            if req_id:
                span.set_attribute("request_id", req_id)

            org_id = org_id_ctx.get()
            if org_id:
                span.set_attribute("org_id", org_id)

            proj_id = project_id_ctx.get()
            if proj_id:
                span.set_attribute("project_id", proj_id)

            try:
                response: Response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
                return response
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
