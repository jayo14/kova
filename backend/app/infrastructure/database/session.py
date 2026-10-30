import asyncio
import logging
import ssl
from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/kova"


def _strip_sslmode(url: str) -> tuple[str, dict]:
    """Extract sslmode from the URL and return (cleaned_url, ssl_kwargs).

    asyncpg does not accept the libpq 'sslmode' query parameter; it uses
    'ssl' (bool or SSLContext) instead. We strip sslmode from the URL so
    SQLAlchemy doesn't forward it to asyncpg, and add the proper 'ssl'
    connect arg based on the sslmode value.
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    ssl_mode_values = query_params.pop("sslmode", None)

    ssl_kwargs: dict = {}
    if ssl_mode_values:
        ssl_mode = ssl_mode_values[0]
        if ssl_mode in ("require", "verify-ca", "verify-full"):
            ssl_context = ssl.create_default_context()
            if ssl_mode == "verify-full":
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED
            else:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            ssl_kwargs["ssl"] = ssl_context

    cleaned_query = urlencode(query_params, doseq=True)
    cleaned_url = urlunparse(parsed._replace(query=cleaned_query))
    return cleaned_url, ssl_kwargs


def _create_engine_safely(url: str) -> AsyncEngine:
    connect_args: dict = {
        "server_settings": {
            "tcp_keepalives_idle": "60",
            "tcp_keepalives_interval": "10",
            "tcp_keepalives_count": "5",
        },
        "command_timeout": 60,
    }

    cleaned_url, ssl_kwargs = _strip_sslmode(url)
    connect_args.update(ssl_kwargs)

    try:
        return create_async_engine(
            cleaned_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=300,
            connect_args=connect_args,
        )
    except Exception as e:
        logger.error(
            "Failed to initialize database engine for URL (%s): %s. Falling back to default URL (%s).",
            cleaned_url,
            e,
            DEFAULT_DATABASE_URL,
        )
        fallback_url, fallback_ssl = _strip_sslmode(DEFAULT_DATABASE_URL)
        fallback_connect_args: dict = {
            "server_settings": {
                "tcp_keepalives_idle": "60",
                "tcp_keepalives_interval": "10",
                "tcp_keepalives_count": "5",
            },
            "command_timeout": 60,
        }
        fallback_connect_args.update(fallback_ssl)
        return create_async_engine(
            fallback_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=300,
            connect_args=fallback_connect_args,
        )


engine = _create_engine_safely(settings.DATABASE_URL)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


from fastapi import Depends


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except asyncio.CancelledError:
            try:
                await asyncio.shield(session.rollback())
            except Exception:
                pass
            raise
        except Exception:
            try:
                await asyncio.shield(session.rollback())
            except Exception:
                pass
            raise


async def get_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    return db

