import json
import logging
import socket
import ssl
import threading
import time

from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun, worker_ready, worker_shutdown
from kombu import Exchange, Queue
import redis

from app.config.settings import settings
from app.observability.metrics import WORKER_CONCURRENT_EXECUTIONS
from app.observability.tracing import get_tracer

logger = logging.getLogger(__name__)

# Kova stores all task progress, states, events, and discoveries directly in
# PostgreSQL and streams them via Redis pub/sub. Celery's result backend is
# entirely unneeded and its async pub/sub consumer permanently crashes the
# Celery application with "Retry limit exceeded while trying to reconnect to
# the Celery result store backend" if Redis drops connections for > 20s.
# We disable the result backend by default (backend=None).
result_backend = None
if settings.ENABLE_CELERY_RESULT_BACKEND and settings.CELERY_RESULT_BACKEND:
    result_backend = str(settings.CELERY_RESULT_BACKEND).strip() or None

celery_app = Celery(
    "kova",
    broker=settings.CELERY_BROKER_URL,
    backend=result_backend,
)


def _get_ssl_config(url: str | None) -> dict | None:
    if not url or "rediss://" not in str(url):
        return None
    ssl_reqs = (settings.REDIS_SSL_CERT_REQS or "none").lower()
    reqs_map = {
        "required": ssl.CERT_REQUIRED,
        "optional": ssl.CERT_OPTIONAL,
        "none": ssl.CERT_NONE,
    }
    cert_reqs = reqs_map.get(ssl_reqs, ssl.CERT_NONE)
    cfg: dict = {"ssl_cert_reqs": cert_reqs}
    if settings.REDIS_SSL_CA_CERTS:
        cfg["ca_certs"] = settings.REDIS_SSL_CA_CERTS
    return cfg


q_prefix = settings.CELERY_QUEUE_PREFIX
default_queue = f"{q_prefix}kova-free"

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    worker_prefetch_multiplier=1,
    result_backend_transport_options={
        "retry_on_timeout": True,
        "socket_timeout": 30.0,
        "socket_connect_timeout": 30.0,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "max_retries": None,
    },
    broker_transport_options={
        "retry_on_timeout": True,
        "socket_timeout": 30.0,
        "socket_connect_timeout": 30.0,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "visibility_timeout": 43200,
        "max_retries": None,
    },
    # Soft limit sits above the exploration wall-clock budget (600s) so the task
    # gets a graceful cleanup window before the recovery watchdog declares it
    # abandoned at 660s. The hard kill is raised per-task to 3660s.
    soft_time_limit=630,
    task_default_queue=default_queue,
    task_default_exchange=default_queue,
    task_default_routing_key=default_queue,
    task_queues=[
        Queue(f"{q_prefix}kova-free", Exchange(f"{q_prefix}kova-free", type="direct"), routing_key=f"{q_prefix}kova-free"),
        Queue(f"{q_prefix}kova-pro", Exchange(f"{q_prefix}kova-pro", type="direct"), routing_key=f"{q_prefix}kova-pro"),
        Queue(f"{q_prefix}kova-enterprise", Exchange(f"{q_prefix}kova-enterprise", type="direct"), routing_key=f"{q_prefix}kova-enterprise"),
    ],
    broker_use_ssl=_get_ssl_config(str(settings.CELERY_BROKER_URL)),
    redis_backend_use_ssl=_get_ssl_config(str(settings.CELERY_RESULT_BACKEND)) if result_backend else None,
)

celery_app.autodiscover_tasks(["app.workers.tasks"])


def get_queue_for_plan(plan: str | None) -> str:
    """Route Celery tasks by organization plan to dedicated worker queues."""
    clean_plan = str(plan).lower() if plan else "free"
    prefix = settings.CELERY_QUEUE_PREFIX
    if clean_plan == "enterprise":
        return f"{prefix}kova-enterprise"
    if clean_plan == "pro":
        return f"{prefix}kova-pro"
    return f"{prefix}kova-free"


# --- Celery Worker Liveness Heartbeat ---
_heartbeat_thread: threading.Thread | None = None
_heartbeat_stop = threading.Event()


def _run_worker_heartbeat(hostname: str) -> None:
    key = f"{settings.REDIS_KEY_PREFIX}worker:alive:{hostname}"
    kwargs: dict = {
        "decode_responses": True,
        "socket_timeout": 5.0,
        "socket_connect_timeout": 5.0,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "retry_on_timeout": True,
    }
    if "rediss://" in str(settings.REDIS_URL):
        reqs_map = {"required": ssl.CERT_REQUIRED, "optional": ssl.CERT_OPTIONAL, "none": ssl.CERT_NONE}
        kwargs["ssl_cert_reqs"] = reqs_map.get((settings.REDIS_SSL_CERT_REQS or "none").lower(), ssl.CERT_NONE)
        if settings.REDIS_SSL_CA_CERTS:
            kwargs["ssl_ca_certs"] = settings.REDIS_SSL_CA_CERTS

    client = None
    while not _heartbeat_stop.is_set():
        try:
            if client is None:
                client = redis.from_url(settings.REDIS_URL, **kwargs)
            val = json.dumps({"hostname": hostname, "timestamp": time.time(), "prefix": settings.CELERY_QUEUE_PREFIX})
            client.set(key, val, ex=15)
        except Exception as exc:
            logger.debug("Failed writing worker heartbeat for %s: %s", hostname, exc)
            if client:
                try:
                    client.close()
                except Exception:
                    pass
                client = None
        _heartbeat_stop.wait(5.0)

    if client:
        try:
            client.delete(key)
            client.close()
        except Exception:
            pass


@worker_ready.connect
def on_worker_ready(sender=None, **kwargs):
    global _heartbeat_thread
    hostname = getattr(sender, "hostname", None) or socket.gethostname()
    _heartbeat_stop.clear()
    _heartbeat_thread = threading.Thread(target=_run_worker_heartbeat, args=(hostname,), daemon=True)
    _heartbeat_thread.start()
    logger.info("Worker heartbeat loop started for %s (TTL=15s, refresh=5s)", hostname)


@worker_shutdown.connect
def on_worker_shutdown(sender=None, **kwargs):
    _heartbeat_stop.set()
    logger.info("Worker heartbeat shutdown requested")


# --- Celery Signals for Observability & Metrics ---
_active_spans = {}


@task_prerun.connect
def on_task_prerun(sender=None, task_id=None, task=None, args=None, kwargs=None, **_):
    queue = getattr(task.request, "delivery_info", {}).get("routing_key", "default") if task and hasattr(task, "request") else "default"
    WORKER_CONCURRENT_EXECUTIONS.labels(queue_name=queue).inc()

    # Start task tracing span
    tracer = get_tracer("kova.celery")
    span_name = f"Celery {task.name if task else sender}"
    span = tracer.start_span(span_name)
    span.set_attribute("celery.task_id", str(task_id))
    span.set_attribute("celery.queue", queue)
    if task_id:
        _active_spans[task_id] = span


@task_postrun.connect
def on_task_postrun(sender=None, task_id=None, task=None, retval=None, state=None, **_):
    queue = getattr(task.request, "delivery_info", {}).get("routing_key", "default") if task and hasattr(task, "request") else "default"
    WORKER_CONCURRENT_EXECUTIONS.labels(queue_name=queue).dec()

    if task_id and task_id in _active_spans:
        span = _active_spans.pop(task_id)
        if state:
            span.set_attribute("celery.state", str(state))
        span.end()


@task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, **_):
    if task_id and task_id in _active_spans:
        span = _active_spans.get(task_id)
        if span and exception:
            span.record_exception(exception)
