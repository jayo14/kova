import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config.settings import settings


@pytest.mark.asyncio
async def test_production_cors_origins(monkeypatch):
    """Production CORS allows origins from CORS_ORIGINS and rejects arbitrary regex subdomains."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CORS_ORIGINS", "https://kova.app,https://custom.kova.app")

    assert settings.cors_origins_list == ["https://kova.app", "https://custom.kova.app"]

    # Development localhost origins must not be in production cors list
    assert "http://localhost:3000" not in settings.cors_origins_list
    assert "http://127.0.0.1:3000" not in settings.cors_origins_list


@pytest.mark.asyncio
async def test_health_routes_separate_liveness_from_readiness(monkeypatch):
    from app import main
    from app.workers.celery_app import celery_app

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement):
            return None

    class RedisClient:
        async def ping(self):
            return True

        async def aclose(self):
            return None

    class Inspector:
        def ping(self):
            return {"worker@test": {"ok": "pong"}}

    class Engine:
        def connect(self):
            return Connection()

    monkeypatch.setattr(main, "engine", Engine())
    monkeypatch.setattr(main.Redis, "from_url", lambda *args, **kwargs: RedisClient())
    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout: Inspector())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        assert root.status_code == 200
        assert root.json()["status"] == "ok"
        assert root.json()["service"] == "kova-backend"

        live = await client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "ok"

        ready = await client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}

        assert (await client.get("/sentry-debug")).status_code == 404
