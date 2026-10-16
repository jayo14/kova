"""Prometheus metrics registry, definitions, and HTTP tracking middleware."""

from __future__ import annotations

import re
import time
from typing import Optional

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

# 1. HTTP metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests handled by the API",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# 2. Execution metrics
EXECUTIONS_STARTED_TOTAL = Counter(
    "executions_started_total",
    "Total flow and continuous validation executions started",
    ["org_id", "plan", "trigger"],
)

EXECUTIONS_COMPLETED_TOTAL = Counter(
    "executions_completed_total",
    "Total flow and continuous validation executions completed",
    ["org_id", "plan", "status"],
)

EXECUTION_DURATION_SECONDS = Histogram(
    "execution_duration_seconds",
    "Total execution duration in seconds",
    ["org_id", "plan", "status"],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

# 3. Worker metrics
WORKER_QUEUE_DEPTH = Gauge(
    "worker_queue_depth",
    "Current number of pending tasks in Celery queue",
    ["queue_name"],
)

WORKER_CONCURRENT_EXECUTIONS = Gauge(
    "worker_concurrent_executions",
    "Current number of executions actively being processed",
    ["queue_name"],
)

# 4. Reliability & failure metrics
BROWSER_CRASHES_TOTAL = Counter(
    "browser_crashes_total",
    "Total browser and page crashes detected during execution",
    ["org_id"],
)

EVIDENCE_UPLOAD_FAILURES_TOTAL = Counter(
    "evidence_upload_failures_total",
    "Total evidence or screenshot upload failures to S3 storage",
    ["reason"],
)

# 5. AI & Product Graph metrics
AI_INVOCATIONS_TOTAL = Counter(
    "ai_invocations_total",
    "Total AI reasoning invocations and whether suggestions were accepted",
    ["capability", "accepted"],
)

PRODUCT_GRAPH_ENTITIES = Gauge(
    "product_graph_entities",
    "Count of discovered Product Graph entities per project",
    ["project_id", "entity_type"],
)

# Regex to normalize UUIDs and numeric IDs to prevent metric cardinality explosion
UUID_OR_NUM_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\b\d+\b"
)


def normalize_metric_path(path: str) -> str:
    """Normalize variable path parameters to avoid high-cardinality label values."""
    if not path:
        return "/"
    # Replace UUIDs with placeholder
    normalized = UUID_OR_NUM_PATTERN.sub(":id", path)
    # Strip trailing slash if not root
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


class PrometheusMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware tracking request count and latency."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        method = request.method
        raw_path = request.url.path
        normalized_path = normalize_metric_path(raw_path)

        try:
            response: Response = await call_next(request)
            status_code = str(response.status_code)
            return response
        except Exception:
            status_code = "500"
            raise
        finally:
            duration = time.perf_counter() - start_time
            # Record metrics, avoiding high-frequency scrape loop self-recording
            if raw_path != "/metrics":
                HTTP_REQUESTS_TOTAL.labels(
                    method=method, path=normalized_path, status=status_code
                ).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(
                    method=method, path=normalized_path
                ).observe(duration)


# Metric recording helpers
def record_execution_started(org_id: str, plan: str = "free", trigger: str = "manual") -> None:
    EXECUTIONS_STARTED_TOTAL.labels(org_id=str(org_id), plan=str(plan), trigger=str(trigger)).inc()


def record_execution_completed(
    org_id: str, plan: str = "free", status: str = "completed", duration_seconds: float = 0.0
) -> None:
    EXECUTIONS_COMPLETED_TOTAL.labels(org_id=str(org_id), plan=str(plan), status=str(status)).inc()
    if duration_seconds > 0:
        EXECUTION_DURATION_SECONDS.labels(
            org_id=str(org_id), plan=str(plan), status=str(status)
        ).observe(duration_seconds)


def record_browser_crash(org_id: str = "unknown") -> None:
    BROWSER_CRASHES_TOTAL.labels(org_id=str(org_id)).inc()


def record_evidence_upload_failure(reason: str = "network_error") -> None:
    EVIDENCE_UPLOAD_FAILURES_TOTAL.labels(reason=str(reason)).inc()


def record_ai_invocation(capability: str, accepted: bool = True) -> None:
    AI_INVOCATIONS_TOTAL.labels(capability=str(capability), accepted=str(accepted).lower()).inc()


def set_worker_queue_depth(queue_name: str, depth: int) -> None:
    WORKER_QUEUE_DEPTH.labels(queue_name=str(queue_name)).set(depth)


def set_worker_concurrent_executions(queue_name: str, count: int) -> None:
    WORKER_CONCURRENT_EXECUTIONS.labels(queue_name=str(queue_name)).set(count)


def set_product_graph_entities(project_id: str, entity_type: str, count: int) -> None:
    PRODUCT_GRAPH_ENTITIES.labels(project_id=str(project_id), entity_type=str(entity_type)).set(count)


def generate_metrics_text() -> tuple[bytes, str]:
    """Generate Prometheus exposition text format bytes and content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
