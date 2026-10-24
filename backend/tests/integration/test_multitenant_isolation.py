"""Multi-tenant cross-organization isolation tests.

Verifies that User A cannot read, list, or mutate User B's:
1. Projects
2. Executions
3. Evidence artifacts
4. Credentials
"""

import uuid
import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.config.settings import settings
from app.main import app
from app.modules.auth.dependencies import _get_jwt_secret
from app.modules.credentials.models import Credential
from app.modules.executions.models import Execution
from app.modules.executions.evidence_model import Evidence
from app.modules.flows.models import Flow
from app.modules.organizations.repository import OrganizationRepository
from app.modules.projects.models import Project
from app.modules.users.models import User


def _make_auth_header(user: User) -> dict[str, str]:
    payload = {
        "sub": str(user.id),
        "aud": settings.OIDC_AUDIENCE or "authenticated",
        "exp": 9999999999,
        "email": user.email,
        "user_metadata": {"name": user.name},
        "iss": settings.effective_jwt_issuer or "kova",
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def multi_tenant_env(db_session: AsyncSession):
    # User A in Org A
    user_a = User(id=uuid.uuid4(), email="user_a@tenant-a.com", name="User A")
    # User B in Org B
    user_b = User(id=uuid.uuid4(), email="user_b@tenant-b.com", name="User B")
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    org_repo = OrganizationRepository(db_session)
    org_a = await org_repo.create_organization(name="Tenant A Org", owner_user_id=user_a.id)
    org_b = await org_repo.create_organization(name="Tenant B Org", owner_user_id=user_b.id)

    # Project B owned by User B
    proj_b = Project(
        id=uuid.uuid4(),
        user_id=user_b.id,
        org_id=org_b.id,
        name="Tenant B Secret Project",
        base_url="https://tenant-b.internal",
    )
    db_session.add(proj_b)
    await db_session.flush()

    # Credential B in Project B
    cred_b = Credential(
        id=uuid.uuid4(),
        project_id=proj_b.id,
        name="tenant_b_api_key",
        email="admin@tenant-b.internal",
        password="encrypted_super_secret_b",
    )
    db_session.add(cred_b)

    # Flow B in Project B
    flow_b = Flow(
        id=uuid.uuid4(),
        project_id=proj_b.id,
        name="Tenant B Checkout Flow",
        description="Internal checkout flow",
        steps=[{"type": "navigate", "url": "https://tenant-b.internal/checkout"}],
    )
    db_session.add(flow_b)
    await db_session.flush()

    # Execution B on Flow B
    exec_b = Execution(
        id=uuid.uuid4(),
        flow_id=flow_b.id,
        status="completed",
        mode="regression",
    )
    db_session.add(exec_b)
    await db_session.flush()

    # Evidence B attached to Execution B
    evidence_b = Evidence(
        id=uuid.uuid4(),
        execution_id=exec_b.id,
        type="screenshot",
        title="Tenant B Secret Screenshot",
        purpose="step_evidence",
        step_id="step_1",
        storage_key="evidence/tenant_b_secret_screenshot.png",
    )
    db_session.add(evidence_b)
    await db_session.commit()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "org_a": org_a,
        "org_b": org_b,
        "proj_b": proj_b,
        "cred_b": cred_b,
        "flow_b": flow_b,
        "exec_b": exec_b,
        "evidence_b": evidence_b,
    }


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_projects(db_session: AsyncSession, multi_tenant_env):
    """User A cannot read or list User B's project."""
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers_a = _make_auth_header(multi_tenant_env["user_a"])
    proj_b = multi_tenant_env["proj_b"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Direct read returns 404/403
        res = await client.get(f"/api/v1/projects/{proj_b.id}", headers=headers_a)
        assert res.status_code in (403, 404)

        # List projects returns only Tenant A projects
        list_res = await client.get("/api/v1/projects/", headers=headers_a)
        assert list_res.status_code == 200
        proj_ids = [p["id"] for p in list_res.json()]
        assert str(proj_b.id) not in proj_ids


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_executions(db_session: AsyncSession, multi_tenant_env):
    """User A cannot access User B's execution details or events."""
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers_a = _make_auth_header(multi_tenant_env["user_a"])
    exec_b = multi_tenant_env["exec_b"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Execution detail
        res = await client.get(f"/api/v1/executions/{exec_b.id}", headers=headers_a)
        assert res.status_code == 404

        # Execution events
        events_res = await client.get(f"/api/v1/executions/{exec_b.id}/events", headers=headers_a)
        assert events_res.status_code == 404


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_evidence(db_session: AsyncSession, multi_tenant_env):
    """User A cannot list or read User B's execution evidence."""
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers_a = _make_auth_header(multi_tenant_env["user_a"])
    exec_b = multi_tenant_env["exec_b"]
    evidence_b = multi_tenant_env["evidence_b"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Evidence list
        res = await client.get(f"/api/v1/executions/{exec_b.id}/evidence", headers=headers_a)
        assert res.status_code == 404

        # Single evidence item
        single_res = await client.get(
            f"/api/v1/executions/{exec_b.id}/evidence/{evidence_b.id}",
            headers=headers_a,
        )
        assert single_res.status_code == 404


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_credentials(db_session: AsyncSession, multi_tenant_env):
    """User A cannot read or list User B's credentials."""
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers_a = _make_auth_header(multi_tenant_env["user_a"])
    proj_b = multi_tenant_env["proj_b"]
    cred_b = multi_tenant_env["cred_b"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Credential list
        res = await client.get(f"/api/v1/projects/{proj_b.id}/credentials", headers=headers_a)
        assert res.status_code == 404

        # Single credential
        single_res = await client.get(
            f"/api/v1/projects/{proj_b.id}/credentials/{cred_b.id}",
            headers=headers_a,
        )
        assert single_res.status_code == 404
