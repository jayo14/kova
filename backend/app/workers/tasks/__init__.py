"""Celery task registry.

Celery autodiscovery imports ``app.workers.tasks.tasks`` only, so tasks defined
in sibling modules (``exploration``, ``executions``) must be imported here or
they never register with the worker.
"""

from app.workers.tasks import executions, exploration, tasks  # noqa: F401

__all__ = ["executions", "exploration", "tasks"]
