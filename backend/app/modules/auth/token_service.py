import hashlib
import secrets
from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import ApiToken


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_api_token() -> tuple[str, str]:
    """Generate raw token and sha256 hash. Returns (raw_token, token_hash)."""
    raw_token = f"kova_tok_{secrets.token_urlsafe(32)}"
    return raw_token, hash_token(raw_token)


async def create_api_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str = "Default API Token",
) -> tuple[ApiToken, str]:
    raw_token, token_hash = generate_api_token()
    token_obj = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
    )
    db.add(token_obj)
    await db.flush()
    return token_obj, raw_token


async def verify_api_token(
    db: AsyncSession,
    raw_token: str,
) -> ApiToken | None:
    token_hash = hash_token(raw_token)
    stmt = select(ApiToken).where(
        ApiToken.token_hash == token_hash,
        ApiToken.revoked_at.is_(None),
    )
    result = await db.execute(stmt)
    token_obj = result.scalar_one_or_none()
    if token_obj:
        token_obj.last_used_at = datetime.now(timezone.utc)
        await db.flush()
    return token_obj
