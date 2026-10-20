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


@pytest.mark.asyncio
async def test_authenticator_password_form_success():
    from unittest.mock import AsyncMock, MagicMock
    from app.engine.browser.session import SessionState
    from app.modules.flows.auth import Authenticator
    from app.modules.product_graph.schemas import AuthCapability

    cap = AuthCapability(
        project_id=uuid.uuid4(),
        name="authenticate_student",
        persona="student",
        login_url="http://127.0.0.1:8000/login",
        success_url_pattern=r"/dashboard",
    )

    mock_browser = MagicMock()
    mock_browser.page = MagicMock()
    mock_browser.page.url = "http://127.0.0.1:8000/login"
    mock_browser.navigate = AsyncMock()
    mock_browser.fill = AsyncMock()
    mock_browser.click = AsyncMock()
    mock_browser.screenshot = AsyncMock(return_value=b"fake_png")
    mock_browser.save_session_state = AsyncMock(
        return_value=SessionState(cookies=[{"name": "session", "value": "xyz"}])
    )

    mock_input = MagicMock()
    mock_input.is_visible = AsyncMock(return_value=True)
    mock_browser.page.query_selector = AsyncMock(return_value=mock_input)

    async def on_click(*args, **kwargs):
        mock_browser.page.url = "http://127.0.0.1:8000/dashboard"

    mock_browser.click.side_effect = on_click

    mock_cred = MagicMock()
    mock_cred.email = "student@kova.dev"
    mock_cred.password = "ValidPassword123!"

    authenticator = Authenticator()
    res = await authenticator.authenticate(
        capability=cap,
        browser=mock_browser,
        credential=mock_cred,
    )

    assert res.success is True
    assert res.session_state is not None
    assert res.session_state.cookies[0]["value"] == "xyz"
    assert len(res.attempts) >= 1
    assert res.attempts[0].success is True


@pytest.mark.asyncio
async def test_authenticator_password_form_failure_wrong_url():
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.flows.auth import Authenticator
    from app.modules.product_graph.schemas import AuthCapability

    cap = AuthCapability(
        project_id=uuid.uuid4(),
        name="authenticate_student",
        persona="student",
        login_url="http://127.0.0.1:8000/login",
        success_url_pattern=r"/dashboard",
    )

    mock_browser = MagicMock()
    mock_browser.page = MagicMock()
    # Post-submit URL stays on /login (bad credentials)
    mock_browser.page.url = "http://127.0.0.1:8000/login"
    mock_browser.navigate = AsyncMock()
    mock_browser.fill = AsyncMock()
    mock_browser.click = AsyncMock()
    mock_browser.screenshot = AsyncMock(return_value=b"fake_png")

    mock_input = MagicMock()
    mock_input.is_visible = AsyncMock(return_value=True)
    mock_browser.page.query_selector = AsyncMock(return_value=mock_input)

    mock_cred = MagicMock()
    mock_cred.email = "student@kova.dev"
    mock_cred.password = "WrongPassword!"

    authenticator = Authenticator()
    res = await authenticator.authenticate(
        capability=cap,
        browser=mock_browser,
        credential=mock_cred,
    )

    assert res.success is False
    assert res.session_state is None
    assert "did not match success pattern" in (res.failure_reason or "")
    assert len(res.attempts) == 2  # Retried once
    assert all(not a.success for a in res.attempts)


@pytest.mark.asyncio
async def test_project_rbac_viewer_cannot_write(db_session: AsyncSession):
    """Viewer-role user or token returns 403 on PUT /api/v1/projects/{id}/flows/{id}."""
    from app.modules.flows.models import Flow
    from app.modules.organizations.models import ProjectMember
    from app.modules.projects.models import Project

    owner = User(id=uuid.uuid4(), email="owner@test.com", name="Owner")
    viewer = User(id=uuid.uuid4(), email="viewer@test.com", name="Viewer")
    db_session.add_all([owner, viewer])
    await db_session.flush()

    project = Project(id=uuid.uuid4(), user_id=owner.id, name="RBAC Proj", base_url="http://test")
    db_session.add(project)
    await db_session.flush()

    flow = Flow(id=uuid.uuid4(), project_id=project.id, name="Test Flow", steps=[])
    db_session.add(flow)

    member = ProjectMember(id=uuid.uuid4(), project_id=project.id, user_id=viewer.id, role="viewer")
    db_session.add(member)
    await db_session.commit()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        viewer_token = jwt.encode(_auth_payload(sub=str(viewer.id)), _get_jwt_secret(), algorithm="HS256")
        headers = {"Authorization": f"Bearer {viewer_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.put(
                f"/api/v1/projects/{project.id}/flows/{flow.id}",
                headers=headers,
                json={"name": "Modified Flow Name"},
            )
            assert resp.status_code == 403
            assert "insufficient project role" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_project_rbac_tester_can_run(db_session: AsyncSession):
    """Tester-role user succeeds on POST /api/v1/ci/validate."""
    from app.modules.organizations.models import ProjectMember
    from app.modules.projects.models import Project

    owner = User(id=uuid.uuid4(), email="owner2@test.com", name="Owner 2")
    tester = User(id=uuid.uuid4(), email="tester2@test.com", name="Tester 2")
    db_session.add_all([owner, tester])
    await db_session.flush()

    project = Project(id=uuid.uuid4(), user_id=owner.id, name="Tester Proj", base_url="http://test")
    db_session.add(project)
    await db_session.flush()

    member = ProjectMember(id=uuid.uuid4(), project_id=project.id, user_id=tester.id, role="tester")
    db_session.add(member)
    await db_session.commit()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        tester_token = jwt.encode(_auth_payload(sub=str(tester.id)), _get_jwt_secret(), algorithm="HS256")
        headers = {"Authorization": f"Bearer {tester_token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/api/v1/ci/validate",
                headers=headers,
                json={"project_id": str(project.id), "scope": "targeted"},
            )
            assert resp.status_code in (200, 201)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_token_scope_ci_only(db_session: AsyncSession):
    """API token scoped to ci:validate only fails on DELETE /api/v1/projects/{id} with 403."""
    from app.modules.auth.token_service import create_api_token
    from app.modules.projects.models import Project

    user = User(id=uuid.uuid4(), email="ci_scoped@test.com", name="CI Scoped User")
    db_session.add(user)
    await db_session.flush()

    project = Project(id=uuid.uuid4(), user_id=user.id, name="CI Scope Proj", base_url="http://test")
    db_session.add(project)
    await db_session.flush()

    _, raw_token = await create_api_token(db_session, user.id, name="CI Token", scopes=["ci:validate"])
    await db_session.commit()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        headers = {"Authorization": f"Bearer {raw_token}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.delete(
                f"/api/v1/projects/{project.id}",
                headers=headers,
            )
            assert resp.status_code == 403
            assert "missing required scope" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rate_limit_per_user(db_session: AsyncSession):
    """61st request within a minute returns 429 with Retry-After."""
    from app.modules.auth.rate_limiter import rate_limiter

    app.state.rate_limit_override = 60
    rate_limiter.reset_in_memory()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="ratelimit@kova.local",
            password_hash=hash_password("ValidPassword123!"),
        )
        db_session.add(user)
        await db_session.commit()

        token = jwt.encode(_auth_payload(sub=str(user_id)), _get_jwt_secret(), algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # 60 requests pass
            for _ in range(60):
                resp = await c.get("/api/v1/projects/", headers=headers)
                assert resp.status_code == 200

            # 61st request fails with 429 and Retry-After header
            resp61 = await c.get("/api/v1/projects/", headers=headers)
            assert resp61.status_code == 429
            assert "Retry-After" in resp61.headers
            assert int(resp61.headers["Retry-After"]) >= 1
    finally:
        app.state.rate_limit_override = None
        rate_limiter.reset_in_memory()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quota_concurrent_executions(db_session: AsyncSession):
    """Org at capacity -> new execution waits or fails with org_at_capacity."""
    from app.modules.organizations.repository import OrganizationRepository
    from app.modules.organizations.service import OrganizationService

    user = User(id=uuid.uuid4(), email="quota_user@test.com", name="Quota User")
    db_session.add(user)
    await db_session.flush()

    org_repo = OrganizationRepository(db_session)
    org = await org_repo.create_organization(name="Capacity Org", owner_user_id=user.id, plan="free")
    # Set max_concurrent_executions to 1
    quota = await org_repo.get_quota(org.id)
    quota.max_concurrent_executions = 1
    await db_session.commit()

    service = OrganizationService(db_session)
    # 1. Acquire first slot
    slot1 = await service.acquire_execution_slot(org.id, queue_timeout=1)
    assert slot1 is True

    # 2. Second slot exceeds capacity and times out
    slot2 = await service.acquire_execution_slot(org.id, queue_timeout=0.2, poll_interval=0.05)
    assert slot2 is False

    # 3. Release first slot and second succeeds
    await service.release_execution_slot(org.id)
    slot3 = await service.acquire_execution_slot(org.id, queue_timeout=1)
    assert slot3 is True
    await service.release_execution_slot(org.id)



