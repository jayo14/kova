import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/kova"


def _create_engine_safely(url: str) -> AsyncEngine:
    try:
        return create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_recycle=1800,
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
            pool_recycle=1800,
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

