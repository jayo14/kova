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

from app.infrastructure.database.session import get_session
from app.modules.users.models import User
from app.config.settings import settings
from app.modules.auth.dependencies import get_current_user, _get_jwt_secret

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

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token missing subject",
        )

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID in token",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.password_hash = hash_password(req.new_password)
    _USED_RESET_TOKENS.add(token_id)
    await db.commit()

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
