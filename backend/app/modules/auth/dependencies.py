import logging
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_session
from app.config.settings import settings
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)

def _get_jwt_secret() -> str:
    return settings.OIDC_CLIENT_ID if settings.OIDC_CLIENT_ID else "dev-secret-key-change-me"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_session),
) -> User:
    if not credentials:
        if not settings.OIDC_ISSUER_URL:
            default_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
            user_repo = UserRepository(db)
            return await user_repo.get_or_create(default_id, "dev@kova.local", "Dev User")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials
    secret = _get_jwt_secret()

    try:
        decode_options: dict = {"require": ["exp", "sub"]}
        audience = settings.OIDC_AUDIENCE
        issuer = settings.effective_jwt_issuer
        if not audience:
            decode_options["verify_aud"] = False
        if not issuer:
            decode_options["verify_iss"] = False

        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience or None,
            issuer=issuer,
            options=decode_options,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except (jwt.InvalidTokenError, jwt.PyJWTError) as e:
        logger.warning("JWT verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
        )

    email = payload.get("email", "")
    user_meta = payload.get("user_metadata") or {}
    name = user_meta.get("name") or user_meta.get("full_name")

    user_repo = UserRepository(db)
    user = await user_repo.get_or_create(user_id, email, name)
    return user
