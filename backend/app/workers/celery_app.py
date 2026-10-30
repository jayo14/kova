import ssl

from celery import Celery

from app.config.settings import settings

celery_app = Celery(
    "kova",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

from kombu import Queue

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Soft limit sits above the exploration wall-clock budget (600s) so the task
    # gets a graceful cleanup window before the recovery watchdog declares it
    # abandoned at 660s. The hard kill is raised per-task to 3660s.
    soft_time_limit=630,
    task_default_queue="kova-free",
    task_queues=[
        Queue("kova-free", routing_key="kova-free"),
        Queue("kova-pro", routing_key="kova-pro"),
        Queue("kova-enterprise", routing_key="kova-enterprise"),
    ],
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE} if "rediss://" in str(settings.CELERY_BROKER_URL) else None,
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE} if "rediss://" in str(settings.CELERY_RESULT_BACKEND) else None,
)

celery_app.autodiscover_tasks(["app.workers.tasks"])


def get_queue_for_plan(plan: str | None) -> str:
    """Route Celery tasks by organization plan to dedicated worker queues."""
    clean_plan = str(plan).lower() if plan else "free"
    if clean_plan == "enterprise":
        return "kova-enterprise"
    if clean_plan == "pro":
        return "kova-pro"
    return "kova-free"


# --- Celery Signals for Observability & Metrics ---
from celery.signals import task_failure, task_postrun, task_prerun
from app.observability.metrics import WORKER_CONCURRENT_EXECUTIONS
from app.observability.tracing import get_tracer

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


