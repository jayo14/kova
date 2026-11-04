from unittest import mock
import pytest

from app.engine.worker_liveness import (
    WorkerStatus,
    get_queued_status_payload,
)


@pytest.mark.asyncio
async def test_worker_status_worker_alive():
    with mock.patch("app.engine.worker_liveness.get_live_workers", return_value=[{"hostname": "celery@node-1"}]):
        with mock.patch("app.engine.worker_liveness.get_queue_backlog", return_value=(5, 2)):
            payload = await get_queued_status_payload("free")
            assert payload["status"] == WorkerStatus.WORKER_ALIVE.value
            assert payload["worker_alive"] is True
            assert payload["worker_count"] == 1
            assert payload["queue_backlog"] == 5
            assert payload["queue_position"] == 2
            assert "Queued - position 2" in payload["message"]


@pytest.mark.asyncio
async def test_worker_status_no_worker():
    with mock.patch("app.engine.worker_liveness.get_live_workers", return_value=[]):
        with mock.patch("app.engine.worker_liveness.get_queue_backlog", return_value=(3, 1)):
            payload = await get_queued_status_payload("free")
            assert payload["status"] == WorkerStatus.NO_WORKER.value
            assert payload["worker_alive"] is False
            assert payload["worker_count"] == 0
            assert payload["queue_backlog"] == 3
            assert payload["queue_position"] is None
            assert payload["message"] == "No worker is running (queue backlog: 3)"


@pytest.mark.asyncio
async def test_worker_status_unknown_when_redis_down():
    # When Redis throws an error, get_live_workers returns None
    with mock.patch("app.engine.worker_liveness.get_live_workers", return_value=None):
        with mock.patch("app.engine.worker_liveness.get_queue_backlog", return_value=(None, None)):
            payload = await get_queued_status_payload("free")
            assert payload["status"] == WorkerStatus.UNKNOWN.value
            assert payload["worker_alive"] is None
            assert payload["worker_count"] is None
            assert payload["queue_backlog"] is None
            assert payload["queue_position"] is None
            assert payload["message"] == "Can't check worker status (Redis unreachable)"
            assert "No worker is running" not in payload["message"]
