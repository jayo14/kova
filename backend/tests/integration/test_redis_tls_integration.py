import os
import ssl
import pytest
import redis
import redis.asyncio as aioredis

from app.config.settings import settings
from app.core.redis_tls import celery_ssl_options, redispy_ssl_kwargs
from app.workers.celery_app import celery_app


def _get_tls_redis_url() -> str | None:
    for candidate in (str(settings.CELERY_BROKER_URL), str(settings.REDIS_URL), os.getenv("REDIS_URL", "")):
        if "rediss://" in candidate:
            return candidate
    return None


@pytest.mark.skipif(not _get_tls_redis_url(), reason="Remote TLS Redis not configured")
def test_sync_redis_tls_connection():
    url = _get_tls_redis_url()
    kwargs = redispy_ssl_kwargs()
    client = redis.from_url(url, **kwargs)
    assert client.ping() is True
    client.close()


@pytest.mark.skipif(not _get_tls_redis_url(), reason="Remote TLS Redis not configured")
@pytest.mark.asyncio
async def test_async_redis_tls_connection():
    url = _get_tls_redis_url()
    kwargs = redispy_ssl_kwargs()
    client = aioredis.from_url(url, **kwargs)
    assert await client.ping() is True
    await client.aclose()


@pytest.mark.skipif(not _get_tls_redis_url(), reason="Remote TLS Redis not configured")
def test_celery_broker_tls_connection():
    with celery_app.connection_for_read() as conn:
        conn.connect()
        assert conn.connected is True
