from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
import bcrypt as py_bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.infrastructure.database.session import get_session
from app.modules.users.models import User
from app.config.settings import settings
from app.modules.auth.dependencies import get_current_user

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
    # We will use JWT_SECRET_KEY or a dedicated JWT_SECRET environment variable (defaulting to a dev key).
    secret = settings.JWT_SECRET_KEY if settings.JWT_SECRET_KEY else "dev-secret-key-change-me"
    encoded_jwt = jwt.encode(to_encode, secret, algorithm="HS256")
    return encoded_jwt


def hash_password(password: str) -> str:
    return py_bcrypt.hashpw(password.encode("utf-8"), py_bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    return py_bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_session)):
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
