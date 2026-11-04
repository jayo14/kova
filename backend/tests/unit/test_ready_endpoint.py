import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.engine.worker_liveness import WorkerStatus


@pytest.mark.asyncio
async def test_ready_endpoint_healthy():
    """Verify /ready reports ok when Postgres, Redis, and workers are healthy."""
    mock_payload = {
        "status": WorkerStatus.WORKER_ALIVE.value,
        "worker_alive": True,
        "worker_count": 1,
        "queue_backlog": 0,
        "queue_position": 1,
        "message": "Queued - position 1",
    }

    mock_engine = MagicMock()
    mock_cm = AsyncMock()
    mock_cm.execute = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_cm

    with patch("app.main.engine", mock_engine), \
         patch("redis.asyncio.Redis.from_url") as mock_redis_cls, \
         patch("app.engine.worker_liveness.get_queued_status_payload", AsyncMock(return_value=mock_payload)):

        mock_r = AsyncMock()
        mock_r.ping = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_r

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["postgres"]["status"] == "ok"
        assert data["redis"]["status"] == "ok"
        assert data["worker"]["status"] == "WORKER_ALIVE"
        assert data["worker"]["count"] == 1


@pytest.mark.asyncio
async def test_ready_endpoint_degraded_when_no_worker():
    """Verify /ready reports degraded status when worker status is NO_WORKER."""
    mock_payload = {
        "status": WorkerStatus.NO_WORKER.value,
        "worker_alive": False,
        "worker_count": 0,
        "queue_backlog": 5,
        "queue_position": None,
        "message": "No worker is running (queue backlog: 5)",
    }

    mock_engine = MagicMock()
    mock_cm = AsyncMock()
    mock_cm.execute = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_cm

    with patch("app.main.engine", mock_engine), \
         patch("redis.asyncio.Redis.from_url") as mock_redis_cls, \
         patch("app.engine.worker_liveness.get_queued_status_payload", AsyncMock(return_value=mock_payload)):

        mock_r = AsyncMock()
        mock_r.ping = AsyncMock(return_value=True)
        mock_redis_cls.return_value = mock_r

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ready")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["worker"]["status"] == "NO_WORKER"
        assert data["worker"]["count"] == 0


@pytest.mark.asyncio
async def test_server_error_handler_returns_typed_error_for_redis():
    """Verify that unhandled Redis errors return typed REDIS_UNAVAILABLE instead of raw tracebacks."""
    from fastapi import Request
    from app.main import server_error_handler

    mock_request = MagicMock(spec=Request)
    mock_request.headers = {}
    exc = ConnectionError("Redis connection closed by peer")

    response = await server_error_handler(mock_request, exc)
    assert response.status_code == 500
    import json
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "REDIS_UNAVAILABLE"
    assert "retry_hint" in body


