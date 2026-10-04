import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport, AsyncClient
import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, settings
from app.infrastructure.database.session import get_session
from app.main import app
from app.modules.auth.dependencies import get_current_user, _get_jwt_secret
from app.modules.users.models import User
from app.api.routes.auth import hash_password, verify_password


def _auth_payload(**overrides) -> dict:
    """Build a JWT payload for HS256 auth testing."""
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": settings.OIDC_AUDIENCE or "authenticated",
        "exp": 9999999999,
        "email": "test@example.com",
        "user_metadata": {"name": "Test User"},
        "iss": settings.effective_jwt_issuer or "kova",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_get_current_user_valid_token(db_session: AsyncSession):
    user_id = uuid.uuid4()
    payload = _auth_payload(
        sub=str(user_id),
        user_metadata={"name": "Test User"},
    )
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(credentials=credentials, db=db_session)

    assert isinstance(user, User)
    assert user.id == user_id
    assert user.email == "test@example.com"
    assert user.name == "Test User"


@pytest.mark.asyncio
async def test_get_current_user_full_name_fallback(db_session: AsyncSession):
    user_id = uuid.uuid4()
    payload = _auth_payload(
        sub=str(user_id),
        email="fullname@example.com",
        user_metadata={"full_name": "Full Name User"},
    )
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await get_current_user(credentials=credentials, db=db_session)

    assert user.id == user_id
    assert user.name == "Full Name User"


@pytest.mark.asyncio
async def test_get_current_user_expired_token(db_session: AsyncSession):
    payload = _auth_payload(exp=1000000000)  # in the past
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token has expired"


@pytest.mark.asyncio
async def test_get_current_user_invalid_audience(db_session: AsyncSession):
    payload = _auth_payload(aud="wrong_audience")
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


@pytest.mark.asyncio
async def test_get_current_user_missing_sub(db_session: AsyncSession):
    payload = _auth_payload()
    payload.pop("sub")
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token missing subject"


@pytest.mark.asyncio
async def test_get_current_user_invalid_uuid(db_session: AsyncSession):
    payload = _auth_payload(sub="not-a-uuid")
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid user ID in token"


@pytest.mark.asyncio
async def test_get_current_user_invalid_token(db_session: AsyncSession):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.jwt.token")

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


@pytest.mark.asyncio
async def test_production_get_projects_unauthenticated_returns_401(monkeypatch, db_session: AsyncSession):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_session] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/v1/projects/")
            assert resp.status_code == 401
            assert resp.json().get("detail") == "Not authenticated"
    finally:
        app.dependency_overrides.clear()


def test_production_refuses_weak_or_empty_jwt_secret():
    from cryptography.fernet import Fernet
    valid_fernet = Fernet.generate_key().decode()

    # Empty secret
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="", CREDENTIAL_ENCRYPTION_KEY=valid_fernet)

    # Default dev secret
    with pytest.raises(ValueError, match="dev-secret-key-change-me"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="dev-secret-key-change-me", CREDENTIAL_ENCRYPTION_KEY=valid_fernet)

    # Under 32 characters
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="short-secret-key", CREDENTIAL_ENCRYPTION_KEY=valid_fernet)

    # Valid secret passes
    s = Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 32, CREDENTIAL_ENCRYPTION_KEY=valid_fernet)
    assert s.JWT_SECRET_KEY == "a" * 32


@pytest.mark.asyncio
async def test_reset_password_confirm_flow(db_session: AsyncSession):
    from app.api.routes.auth import verify_password
    from app.modules.users.models import User

    # Create test user
    user = User(
        id=uuid.uuid4(),
        email="reset_flow@example.com",
        name="Reset User",
        password_hash="old_hash",
    )
    db_session.add(user)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_session] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # 1. Reset password confirm with token
            reset_token = jwt.encode(
                {"exp": 9999999999, "sub": str(user.id), "type": "reset", "jti": str(uuid.uuid4())},
                _get_jwt_secret(),
                algorithm="HS256",
            )
            
            # Enforce min length of 8
            resp = await c.post(
                "/api/v1/auth/reset-password/confirm",
                json={"token": reset_token, "new_password": "short"},
            )
            assert resp.status_code == 400
            assert "8 characters" in resp.json()["detail"]

            # Must check type == "reset"
            wrong_type_token = jwt.encode(
                {"exp": 9999999999, "sub": str(user.id), "type": "access"},
                _get_jwt_secret(),
                algorithm="HS256",
            )
            resp = await c.post(
                "/api/v1/auth/reset-password/confirm",
                json={"token": wrong_type_token, "new_password": "validNewPassword123!"},
            )
            assert resp.status_code == 400
            assert "Invalid token type" in resp.json()["detail"]

            # Valid confirm
            resp = await c.post(
                "/api/v1/auth/reset-password/confirm",
                json={"token": reset_token, "new_password": "validNewPassword123!"},
            )
            assert resp.status_code == 200

            # Single-use: using the same token again fails
            resp = await c.post(
                "/api/v1/auth/reset-password/confirm",
                json={"token": reset_token, "new_password": "anotherNewPassword123!"},
            )
            assert resp.status_code == 400
            assert "already been used" in resp.json()["detail"]

            # Verify password was updated
            await db_session.refresh(user)
            assert verify_password("validNewPassword123!", user.password_hash)

            # 2. Change password
            auth_token = jwt.encode(
                _auth_payload(sub=str(user.id)),
                _get_jwt_secret(),
                algorithm="HS256",
            )
            resp = await c.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {auth_token}"},
                json={"new_password": "changedPassword123!"},
            )
            assert resp.status_code == 200
            await db_session.refresh(user)
            assert verify_password("changedPassword123!", user.password_hash)

            # 3. Delete account
            resp = await c.delete(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            assert resp.status_code == 200

            # Verify user deleted
            from sqlalchemy import select
            res = await db_session.execute(select(User).where(User.id == user.id))
            assert res.scalar_one_or_none() is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auth_tokens_crud(db_session):
    """Test POST /auth/tokens, GET /auth/tokens, and DELETE /auth/tokens/{id}."""
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user = User(
            id=uuid.uuid4(),
            email="tokens-test@kova.local",
            password_hash=hash_password("ValidPassword123!"),
        )
        db_session.add(user)
        await db_session.commit()

        auth_token = jwt.encode(
            _auth_payload(sub=str(user.id)),
            _get_jwt_secret(),
            algorithm="HS256",
        )
        headers = {"Authorization": f"Bearer {auth_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # 1. Create token
            create_resp = await c.post(
                "/auth/tokens",
                headers=headers,
                json={"name": "My Deploy Token"},
            )
            assert create_resp.status_code == 201
            token_data = create_resp.json()
            token_id = token_data["id"]
            raw_token = token_data["token"]
            assert raw_token.startswith("kova_tok_")

            # 2. List tokens
            list_resp = await c.get("/auth/tokens", headers=headers)
            assert list_resp.status_code == 200
            tokens = list_resp.json()
            assert any(t["id"] == token_id and t["name"] == "My Deploy Token" for t in tokens)

            # 3. Delete token
            del_resp = await c.delete(f"/auth/tokens/{token_id}", headers=headers)
            assert del_resp.status_code == 204

            # 4. Verify no longer in list
            list_resp2 = await c.get("/auth/tokens", headers=headers)
            assert list_resp2.status_code == 200
            assert not any(t["id"] == token_id for t in list_resp2.json())
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reset_password_redis_jti_persists_across_app_restart(db_session):
    """Reset token single-use check must persist in Redis even if in-memory cache is wiped (app restart)."""
    from app.api.routes.auth import _USED_RESET_TOKENS

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user = User(
            id=uuid.uuid4(),
            email="restart-reset@kova.local",
            password_hash=hash_password("InitialPassword123!"),
        )
        db_session.add(user)
        await db_session.commit()

        jti = str(uuid.uuid4())
        reset_token = jwt.encode(
            {
                "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
                "sub": str(user.id),
                "type": "reset",
                "jti": jti,
            },
            _get_jwt_secret(),
            algorithm="HS256",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # 1. First reset call succeeds
            resp1 = await c.post(
                "/auth/reset-password/confirm",
                json={"token": reset_token, "new_password": "NewSecretPassword123!"},
            )
            assert resp1.status_code == 200
            assert resp1.json()["message"] == "Password reset successfully"

            # 2. Simulate app restart: wipe in-memory _USED_RESET_TOKENS
            _USED_RESET_TOKENS.clear()
            assert jti not in _USED_RESET_TOKENS

            # 3. Second reset call MUST still fail because Redis stored the used jti
            resp2 = await c.post(
                "/auth/reset-password/confirm",
                json={"token": reset_token, "new_password": "AnotherSecretPassword123!"},
            )
            assert resp2.status_code == 400
            assert "already been used" in resp2.json()["detail"]
    finally:
        app.dependency_overrides.clear()


