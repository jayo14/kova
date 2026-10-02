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

_jwk_client: PyJWKClient | None = None
_jwk_failed = False


def _get_jwk_client() -> PyJWKClient | None:
    global _jwk_client, _jwk_failed
    if _jwk_failed:
        return None
    if _jwk_client is None:
        project_ref = settings.SUPABASE_PROJECT_REF
        if not project_ref or project_ref == "127.0.0.1":
            if settings.is_production:
                # Production must never silently fall back to a shared dev user:
                # every request would coalesce into one identity with full
                # cross-user access. Refuse instead.
                raise RuntimeError(
                    "Refusing to start: SUPABASE_PROJECT_REF is not configured "
                    "and the dev auth bypass is disabled in production."
                )
            logger.warning("Supabase not configured — auth disabled in dev mode")
            _jwk_failed = True
            return None
        try:
            jwks_url = (
                f"https://{project_ref}"
                ".supabase.co/auth/v1/.well-known/jwks.json"
            )
            _jwk_client = PyJWKClient(jwks_url, cache_keys=True)
        except Exception as e:
            logger.warning("Failed to init JWK client: %s", e)
            _jwk_failed = True
            return None
    return _jwk_client


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_session),
) -> User:
    # Dev mode: allow unauthenticated access with a default user
    # This covers both "Supabase not configured" and "user not logged in locally"
    jwk_client = _get_jwk_client()
    if jwk_client is None:
        if settings.is_production:
            # Belt-and-braces: even if the JWK client was somehow disabled,
            # never issue the shared dev identity in production.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured on this server",
            )
        default_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_repo = UserRepository(db)
        return await user_repo.get_or_create(default_id, "dev@kova.local", "Dev User")

    if not credentials:
        if settings.SUPABASE_PROJECT_REF == "127.0.0.1":
            default_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
            user_repo = UserRepository(db)
            return await user_repo.get_or_create(default_id, "dev@kova.local", "Dev User")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials

    try:
        signing_key = jwk_client.get_signing_key_from_jwt(token)

        decode_options: dict = {"require": ["exp", "sub"]}
        audience = settings.SUPABASE_JWT_AUDIENCE
        issuer = settings.effective_jwt_issuer
        if not audience:
            decode_options["verify_aud"] = False
        if not issuer:
            decode_options["verify_iss"] = False

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
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
