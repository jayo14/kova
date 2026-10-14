import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/kova"


def _create_engine_safely(url: str) -> AsyncEngine:
    connect_args = {}
    if "asyncpg" in url or "postgresql" in url:
        connect_args = {
            "server_settings": {
                "tcp_keepalives_idle": "60",
                "tcp_keepalives_interval": "10",
                "tcp_keepalives_count": "5",
            },
            "command_timeout": 60,
        }

    try:
        return create_async_engine(
            url,
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
            url,
            e,
            DEFAULT_DATABASE_URL,
        )
        return create_async_engine(
            DEFAULT_DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=300,
            connect_args=connect_args,
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

