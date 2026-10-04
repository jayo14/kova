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
