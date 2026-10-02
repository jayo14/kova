from celery import Celery

from app.config.settings import settings

celery_app = Celery(
    "kova",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

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
)

celery_app.autodiscover_tasks(["app.workers.tasks"])
