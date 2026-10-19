import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_current_schema_revision(session: AsyncSession) -> str | None:
    """Retrieve the current applied migration version from alembic_version."""
    try:
        result = await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.debug("Could not query alembic_version: %s", exc)
        return None


async def verify_database_schema(session: AsyncSession) -> dict[str, str | bool | None]:
    """Verify database connectivity and report current schema revision."""
    try:
        await session.execute(text("SELECT 1"))
        rev = await get_current_schema_revision(session)
        logger.info("Database connection established (schema revision: %s)", rev or "untracked")
        return {"connected": True, "revision": rev}
    except Exception as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return {"connected": False, "revision": None, "error": str(exc)}
