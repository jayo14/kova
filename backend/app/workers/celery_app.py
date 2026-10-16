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
    # Soft limit (9 min) allows graceful cleanup before hard kill (10 min)
    soft_time_limit=540,
    task_default_queue="kova-free",
    task_queues=[
        Queue("kova-free", routing_key="kova-free"),
        Queue("kova-pro", routing_key="kova-pro"),
        Queue("kova-enterprise", routing_key="kova-enterprise"),
    ],
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

