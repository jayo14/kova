from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
import bcrypt as py_bcrypt
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from app.modules.email.service import email_service
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

import logging
import redis.asyncio as aioredis

from app.infrastructure.database.session import get_session
from app.modules.users.models import User
from app.config.settings import settings
from app.modules.auth.dependencies import get_current_user, _get_jwt_secret

logger = logging.getLogger(__name__)

async def _get_redis() -> aioredis.Redis | None:
    try:
        kwargs: dict[str, Any] = {"decode_responses": True}
        if settings.REDIS_URL.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = "none"
        return aioredis.from_url(settings.REDIS_URL, **kwargs)
    except Exception as e:
        logger.debug("Failed to connect to redis: %s", e)
        return None

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode = {
        "exp": expires,
        "sub": str(user.id),
        "email": user.email,
        "user_metadata": {"name": user.name},
        "iss": settings.effective_jwt_issuer or "kova",
        "aud": settings.OIDC_AUDIENCE or "authenticated",
    }
    # Since we are replacing the external Identity Provider, we must sign the JWT ourselves.
    secret = _get_jwt_secret()
    encoded_jwt = jwt.encode(to_encode, secret, algorithm="HS256")
    return encoded_jwt


def hash_password(password: str) -> str:
    return py_bcrypt.hashpw(password.encode("utf-8"), py_bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    return py_bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == req.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    new_user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    token = create_access_token(new_user)
    
    # Send welcome email asynchronously
    html_content = f"<h2>Welcome to Kova, {new_user.name or 'User'}!</h2><p>Your autonomous software testing journey starts here.</p>"
    background_tasks.add_task(email_service.send_email, new_user.email, "Welcome to Kova", html_content)
    
    return TokenResponse(
        access_token=token,
        user={"id": str(new_user.id), "email": new_user.email, "name": new_user.name},
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        user={"id": str(user.id), "email": user.email, "name": user.name},
    )


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "email": user.email, "name": user.name}

class ResetPasswordRequest(BaseModel):
    email: EmailStr

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    
    if user:
        # Generate a temporary reset JWT
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        jti = str(uuid.uuid4())
        to_encode = {"exp": expires, "sub": str(user.id), "type": "reset", "jti": jti}
        secret = _get_jwt_secret()
        reset_token = jwt.encode(to_encode, secret, algorithm="HS256")
        
        frontend_url = settings.FRONTEND_URL.rstrip("/")
        reset_link = f"{frontend_url}/auth/reset-password?token={reset_token}"
        
        html_content = f"<h2>Password Reset</h2><p>Click <a href='{reset_link}'>here</a> to reset your password. This link expires in 1 hour.</p>"
        background_tasks.add_task(email_service.send_email, user.email, "Reset your Kova password", html_content)
        
    # Always return success to prevent email enumeration
    return {"message": "If that email exists, we sent a password reset link."}


_USED_RESET_TOKENS: set[str] = set()


class ResetPasswordConfirmRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    new_password: str | None = None
    password: str | None = None


@router.post("/reset-password/confirm")
async def confirm_reset_password(
    req: ResetPasswordConfirmRequest,
    db: AsyncSession = Depends(get_session),
):
    if len(req.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long",
        )

    try:
        secret = _get_jwt_secret()
        payload = jwt.decode(req.token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired",
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token",
        )

    if payload.get("type") != "reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token type",
        )

    token_id = payload.get("jti") or req.token
    if token_id in _USED_RESET_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has already been used",
        )

    redis_client = await _get_redis()
    redis_key = f"used_reset_jti:{token_id}"
    if redis_client:
        try:
            val = await redis_client.get(redis_key)
            if val:
                _USED_RESET_TOKENS.add(token_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reset token has already been used",
                )
        except HTTPException:
            await redis_client.aclose()
            raise
        except Exception as e:
            logger.debug("Redis error checking reset jti: %s", e)

    sub = payload.get("sub")
    if not sub:
        if redis_client:
            await redis_client.aclose()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token missing subject",
        )

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        if redis_client:
            await redis_client.aclose()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID in token",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        if redis_client:
            await redis_client.aclose()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.password_hash = hash_password(req.new_password)
    _USED_RESET_TOKENS.add(token_id)
    await db.commit()

    if redis_client:
        try:
            exp = payload.get("exp")
            ttl = 3600
            if exp:
                remaining = int(exp - datetime.now(timezone.utc).timestamp())
                ttl = max(remaining, 60)
            await redis_client.set(redis_key, "1", ex=ttl)
        except Exception as e:
            logger.debug("Redis error storing reset jti: %s", e)
        finally:
            await redis_client.aclose()

    return {"message": "Password reset successfully"}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    pwd = req.new_password or req.password
    if not pwd or len(pwd) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long",
        )

    user.password_hash = hash_password(pwd)
    await db.commit()
    return {"message": "Password updated successfully"}


@router.delete("/me")
async def delete_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await db.delete(user)
    await db.commit()
    return {"message": "Account deleted successfully"}


class CreateApiTokenRequest(BaseModel):
    name: str = "Default Token"


class ApiTokenResponse(BaseModel):
    id: uuid.UUID
    name: str
    token: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None


@router.post("/tokens", response_model=ApiTokenResponse, status_code=201)
async def create_token(
    data: CreateApiTokenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Generate a new API token for CI or programmatic access."""
    from app.modules.auth.token_service import create_api_token
    token_obj, raw_token = await create_api_token(db, user.id, data.name)
    await db.commit()
    return ApiTokenResponse(
        id=token_obj.id,
        name=token_obj.name,
        token=raw_token,
        created_at=token_obj.created_at,
        last_used_at=token_obj.last_used_at,
    )


@router.get("/tokens", response_model=list[ApiTokenResponse])
async def list_tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List all active API tokens for current user."""
    from app.modules.auth.token_service import list_api_tokens
    tokens = await list_api_tokens(db, user.id)
    return [
        ApiTokenResponse(
            id=t.id,
            name=t.name,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
        )
        for t in tokens
    ]


@router.delete("/tokens/{id}", status_code=204)
async def delete_token(
    id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Revoke an API token."""
    from app.modules.auth.token_service import delete_api_token
    deleted = await delete_api_token(db, user.id, id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API token not found",
        )
    await db.commit()
    return None

