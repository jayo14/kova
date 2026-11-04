import pytest
from celery.backends.base import DisabledBackend
from app.workers.celery_app import celery_app
from app.workers.tasks.exploration import run_exploration
from app.workers.tasks.executions import run_execution
from app.workers.tasks.tasks import run_multiple_executions


def test_celery_result_backend_disabled():
    assert celery_app.backend_cls == "disabled"
    assert isinstance(celery_app.backend, DisabledBackend)
    assert celery_app.conf.task_ignore_result is True
    assert run_exploration.ignore_result is True
    assert run_execution.ignore_result is True
    assert run_multiple_executions.ignore_result is True
