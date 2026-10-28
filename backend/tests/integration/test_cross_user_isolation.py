"""Cross-user tenancy isolation acceptance tests.

Proves user A cannot read, modify, or download anything belonging to user B:
exploration sessions, flows, executions, traces, screenshots, credentials.
Authorization is identical in every environment (no production bypass).
"""

import uuid

import jwt
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.api.routes.exploration import _get_authorized_session
from app.config.settings import settings
from app.main import app
from app.modules.auth.dependencies import _get_jwt_secret
from app.modules.credentials.models import Credential
from app.modules.credentials.repository import CredentialRepository
from app.modules.credentials.crypto import encrypt_credential
from app.modules.executions.models import Execution
from app.modules.executions.evidence_model import Evidence
from app.modules.flows.models import Flow
from app.modules.exploration.models import ExplorationSession, ExplorationStatus
from app.modules.projects.models import Project
from app.modules.users.models import User


def _make_auth_header(user: User) -> dict[str, str]:
    payload = {
        "sub": str(user.id),
        "aud": settings.OIDC_AUDIENCE or "authenticated",
        "exp": 9999999999,
        "email": user.email,
        "iss": settings.effective_jwt_issuer or "kova",
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def isolated_env(db_session: AsyncSession):
    """User A and user B, each with a project and owned resources."""
    user_a = User(id=uuid.uuid4(), email="iso_user_a@example.com", name="User A")
    user_b = User(id=uuid.uuid4(), email="iso_user_b@example.com", name="User B")
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    proj_a = Project(
        id=uuid.uuid4(),
        user_id=user_a.id,
        name="Tenant A Project",
        base_url="https://tenant-a.internal",
    )
    proj_b = Project(
        id=uuid.uuid4(),
        user_id=user_b.id,
        name="Tenant B Project",
        base_url="https://tenant-b.internal",
    )
    db_session.add_all([proj_a, proj_b])
    await db_session.flush()

    cred_repo = CredentialRepository(db_session)
    cred_a = await cred_repo.create(
        project_id=proj_a.id,
        name="tenant_a_login",
        email="a@tenant-a.internal",
        password="tenant_a_secret",
    )
    cred_b = Credential(
        id=uuid.uuid4(),
        project_id=proj_b.id,
        name="tenant_b_login",
        email="b@tenant-b.internal",
        password=encrypt_credential("tenant_b_secret"),
    )
    db_session.add(cred_b)

    flow_a = Flow(
        id=uuid.uuid4(),
        project_id=proj_a.id,
        name="Tenant A Flow",
        steps=[{"type": "navigate", "url": "https://tenant-a.internal"}],
        version=1,
    )
    flow_b = Flow(
        id=uuid.uuid4(),
        project_id=proj_b.id,
        name="Tenant B Flow",
        steps=[{"type": "navigate", "url": "https://tenant-b.internal"}],
        version=1,
    )
    db_session.add_all([flow_a, flow_b])
    await db_session.flush()

    exec_a = Execution(
        id=uuid.uuid4(),
        flow_id=flow_a.id,
        status="completed",
        mode="regression",
        flow_snapshot={},
    )
    exec_b = Execution(
        id=uuid.uuid4(),
        flow_id=flow_b.id,
        status="completed",
        mode="regression",
        flow_snapshot={},
    )
    db_session.add_all([exec_a, exec_b])
    await db_session.flush()

    evidence_b = Evidence(
        id=uuid.uuid4(),
        execution_id=exec_b.id,
        type="screenshot",
        title="Tenant B Secret Screenshot",
        purpose="step_evidence",
        step_id="step_1",
        storage_key="evidence/tenant_b_secret.png",
    )
    db_session.add(evidence_b)

    session_a = ExplorationSession(
        id=uuid.uuid4(),
        user_id=user_a.id,
        project_id=proj_a.id,
        url="https://tenant-a.internal/",
        status=ExplorationStatus.CREATED.value,
    )
    session_b = ExplorationSession(
        id=uuid.uuid4(),
        user_id=user_b.id,
        project_id=proj_b.id,
        url="https://tenant-b.internal/",
        status=ExplorationStatus.CREATED.value,
    )
    db_session.add_all([session_a, session_b])
    await db_session.commit()

    return {
        "user_a": user_a,
        "user_b": user_b,
        "proj_a": proj_a,
        "proj_b": proj_b,
        "cred_a": cred_a,
        "cred_b": cred_b,
        "flow_a": flow_a,
        "flow_b": flow_b,
        "exec_a": exec_a,
        "exec_b": exec_b,
        "evidence_b": evidence_b,
        "session_a": session_a,
        "session_b": session_b,
    }


async def _client_with_user(db_session: AsyncSession, user: User):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    await client.__aenter__()
    return client, (_make_auth_header(user), app)


def _teardown_app():
    app.dependency_overrides.clear()


# ── Exploration ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_exploration_session(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    session_b = isolated_env["session_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(f"/api/v1/exploration/{session_b.id}", headers=headers_a)
        assert res.status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_user_a_cannot_modify_user_b_exploration_session(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    session_b = isolated_env["session_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        for method, path, body in (
            ("post", f"/api/v1/exploration/{session_b.id}/credentials", {"email": "x@y.com", "password": "p"}),
            ("post", f"/api/v1/exploration/{session_b.id}/answer", {"question_id": "q1", "answer": "a1"}),
            ("post", f"/api/v1/exploration/{session_b.id}/cancel", {}),
            ("post", f"/api/v1/exploration/{session_b.id}/navigate/back", {}),
        ):
            res = await getattr(client, method)(path, headers=headers_a, json=body)
            assert res.status_code in (403, 404), f"{method.upper()} {path} -> {res.status_code}"
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_user_a_cannot_list_user_b_exploration_credentials(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    session_b = isolated_env["session_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(
            f"/api/v1/exploration/{session_b.id}/credentials", headers=headers_a
        )
        assert res.status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_screenshot(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    session_b = isolated_env["session_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(
            f"/api/v1/exploration/screenshots/{session_b.id}_00000000-0000-0000-0000-000000000000.png",
            headers=headers_a,
        )
        assert res.status_code == 404
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_user_a_can_access_own_exploration_resources(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    session_a = isolated_env["session_a"]
    flow_a = isolated_env["flow_a"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(f"/api/v1/exploration/{session_a.id}", headers=headers_a)
        assert res.status_code == 200
        assert res.json()["id"] == str(session_a.id)

        res = await client.get(f"/api/v1/flows/{flow_a.id}", headers=headers_a)
        assert res.status_code == 200
        assert res.json()["id"] == str(flow_a.id)

        res = await client.get(f"/api/v1/projects/{isolated_env['proj_a'].id}/credentials", headers=headers_a)
        assert res.status_code == 200
        ids = [c["id"] for c in res.json()]
        assert str(isolated_env["cred_a"].id) in ids
        # Passwords never in responses
        for c in res.json():
            assert "password" not in c
    finally:
        await client.aclose()
        _teardown_app()


# ── Flows ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_a_cannot_read_or_update_user_b_flow(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    flow_b = isolated_env["flow_b"]
    proj_b = isolated_env["proj_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(f"/api/v1/flows/{flow_b.id}", headers=headers_a)
        assert res.status_code in (403, 404)

        res = await client.put(
            f"/api/v1/flows/{flow_b.id}", headers=headers_a, json={"name": "hacked"}
        )
        assert res.status_code in (403, 404)

        # Nested project-scoped route: flow must belong to the project in the path
        res = await client.put(
            f"/api/v1/projects/{proj_b.id}/flows/{flow_b.id}",
            headers=headers_a,
            json={"name": "hacked"},
        )
        assert res.status_code in (403, 404)

        # Cross-wiring: a flow of project A addressed under project B's path is rejected
        res = await client.put(
            f"/api/v1/projects/{proj_b.id}/flows/{isolated_env['flow_a'].id}",
            headers=headers_a,
            json={"name": "hacked"},
        )
        assert res.status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_user_a_cannot_create_execution_on_user_b_flow(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    flow_b = isolated_env["flow_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.post(
            f"/api/v1/flows/{flow_b.id}/executions", headers=headers_a, json={}
        )
        assert res.status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


# ── Executions / traces / evidence ────────────────────────────

@pytest.mark.asyncio
async def test_user_a_cannot_access_user_b_execution(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    exec_b = isolated_env["exec_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        assert (await client.get(f"/api/v1/executions/{exec_b.id}", headers=headers_a)).status_code in (
            403,
            404,
        )
        assert (
            await client.get(f"/api/v1/executions/{exec_b.id}/events", headers=headers_a)
        ).status_code in (403, 404)
        assert (
            await client.post(f"/api/v1/executions/{exec_b.id}/cancel", headers=headers_a)
        ).status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_trace_download_resolved_by_execution_id_and_authorized(
    db_session: AsyncSession, isolated_env, tmp_path
):
    """Trace comes from the execution's evidence record only: no shared-directory fallback."""
    headers_a = _make_auth_header(isolated_env["user_a"])
    headers_b = _make_auth_header(isolated_env["user_b"])
    exec_a = isolated_env["exec_a"]

    # A trace file sitting in a shared directory must NOT be served for exec_a
    # when no evidence row references it.
    shared_trace = tmp_path / f"trace_{exec_a.id}.zip"
    shared_trace.write_bytes(b"trace bait")

    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(f"/api/v1/executions/{exec_a.id}/trace", headers=headers_a)
        assert res.status_code == 404

        # Now record the trace against the execution in the evidence table.
        db_session.add(
            Evidence(
                id=uuid.uuid4(),
                execution_id=exec_a.id,
                type="trace",
                title="Tenant A trace",
                purpose="trace",
                step_id="step_1",
                storage_key=str(shared_trace),
                trace_url=f"file://{shared_trace}",
            )
        )
        await db_session.commit()

        res = await client.get(f"/api/v1/executions/{exec_a.id}/trace", headers=headers_a)
        assert res.status_code == 200
        assert res.content == b"trace bait"

        # User B still cannot download it.
        client_b, (_hb, _app_b) = await _client_with_user(db_session, isolated_env["user_b"])
        try:
            res_b = await client_b.get(
                f"/api/v1/executions/{exec_a.id}/trace", headers=headers_b
            )
            assert res_b.status_code in (403, 404)
            # A report signature must not bypass trace ownership checks.
            signed_bypass = await client_b.get(
                f"/api/v1/executions/{exec_a.id}/trace?signature=not-a-user-session",
                headers=headers_b,
            )
            assert signed_bypass.status_code in (403, 404)
        finally:
            await client_b.aclose()
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_user_a_cannot_access_user_b_evidence(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    exec_b = isolated_env["exec_b"]
    evidence_b = isolated_env["evidence_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        assert (
            await client.get(f"/api/v1/executions/{exec_b.id}/evidence", headers=headers_a)
        ).status_code in (403, 404)
        assert (
            await client.get(
                f"/api/v1/executions/{exec_b.id}/evidence/{evidence_b.id}",
                headers=headers_a,
            )
        ).status_code in (403, 404)
        assert (
            await client.get(
                f"/api/v1/executions/{exec_b.id}/evidence/{evidence_b.id}/file",
                headers=headers_a,
            )
        ).status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


# ── Credentials ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_a_cannot_read_user_b_credentials(
    db_session: AsyncSession, isolated_env
):
    headers_a = _make_auth_header(isolated_env["user_a"])
    proj_b = isolated_env["proj_b"]
    cred_b = isolated_env["cred_b"]
    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        assert (
            await client.get(f"/api/v1/projects/{proj_b.id}/credentials", headers=headers_a)
        ).status_code in (403, 404)
        assert (
            await client.get(
                f"/api/v1/projects/{proj_b.id}/credentials/{cred_b.id}", headers=headers_a
            )
        ).status_code in (403, 404)
    finally:
        await client.aclose()
        _teardown_app()


@pytest.mark.asyncio
async def test_exploration_credentials_fallback_does_not_leak_inaccessible_projects(
    db_session: AsyncSession, isolated_env
):
    """Cross-host fallback may only return credentials from projects the caller accesses."""
    headers_a = _make_auth_header(isolated_env["user_a"])
    session_a = isolated_env["session_a"]
    proj_b = isolated_env["proj_b"]

    # Point session A's URL at project B's host: the fallback may only consider
    # projects user A can access, so project B's credentials must not surface.
    session_a.url = "https://tenant-b.internal/"
    await db_session.commit()

    client, (_headers, _app) = await _client_with_user(db_session, isolated_env["user_a"])
    try:
        res = await client.get(
            f"/api/v1/exploration/{session_a.id}/credentials", headers=headers_a
        )
        assert res.status_code == 200
        ids = [c["id"] for c in res.json()]
        assert str(isolated_env["cred_b"].id) not in ids
    finally:
        await client.aclose()
        _teardown_app()


# ── Authorization identical in every environment ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "development", "test"])
async def test_exploration_session_authorization_has_no_environment_bypass(
    db_session: AsyncSession, isolated_env, monkeypatch, environment
):
    """_get_authorized_session rejects cross-user access in every environment."""
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    session_a = isolated_env["session_a"]

    with pytest.raises(HTTPException) as exc_info:
        await _get_authorized_session(str(session_a.id), isolated_env["user_b"].id, db_session)
    assert exc_info.value.status_code == 403
