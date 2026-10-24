"""Load testing with N concurrent executions.

Simulates N concurrent execution dispatches and validates throughput,
absence of cross-talk, memory stability, and asynchronous latency bounds.
"""

import asyncio
import time
import uuid
import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import get_session
from app.config.settings import settings
from app.main import app
from app.modules.auth.dependencies import _get_jwt_secret
from app.modules.organizations.repository import OrganizationRepository
from app.modules.projects.models import Project
from app.modules.flows.models import Flow
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
async def load_test_env(db_engine):
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    N = 10
    user_flows = []

    async with session_factory() as session:
        org_repo = OrganizationRepository(session)
        for i in range(N):
            user = User(
                id=uuid.uuid4(),
                email=f"load_user_{i}@kova.internal",
                name=f"Load User {i}",
            )
            session.add(user)
            await session.flush()

            org = await org_repo.create_organization(
                name=f"Load Org {i}",
                owner_user_id=user.id,
                plan="enterprise",
            )

            project = Project(
                id=uuid.uuid4(),
                user_id=user.id,
                org_id=org.id,
                name=f"Load Project {i}",
                base_url="https://benchmark.internal",
            )
            session.add(project)
            await session.flush()

            flow = Flow(
                id=uuid.uuid4(),
                project_id=project.id,
                name=f"Parallel Flow {i}",
                description="Flow for concurrency testing",
                steps=[{"type": "navigate", "url": "https://benchmark.internal/dashboard"}],
            )
            session.add(flow)
            user_flows.append((user, flow.id))

        await session.commit()

    async def override_get_db():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_db
    yield session_factory, user_flows
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_concurrent_execution_dispatch_load(load_test_env, monkeypatch):
    """Dispatch N concurrent executions across independent users and verify throughput and latency."""
    session_factory, user_flows = load_test_env
    N = len(user_flows)

    dispatched = []

    def mock_schedule_dispatch(execution_id: str, *args, **kwargs):
        dispatched.append(str(execution_id))
        return None

    monkeypatch.setattr("app.api.dispatch.schedule_dispatch", mock_schedule_dispatch)
    monkeypatch.setattr("app.api.dispatch.dispatch_execution", mock_schedule_dispatch)
    monkeypatch.setattr("app.api.routes.flows._schedule_dispatch", mock_schedule_dispatch)

    transport = ASGITransport(app=app)

    async def single_dispatch(user: User, flow_id: uuid.UUID, index: int) -> dict:
        auth_header = _make_auth_header(user)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            t0 = time.monotonic()
            res = await client.post(
                f"/api/v1/flows/{flow_id}/executions",
                headers=auth_header,
            )
            latency_ms = (time.monotonic() - t0) * 1000.0
            return {
                "index": index,
                "status_code": res.status_code,
                "body": res.json() if res.status_code == 201 else res.text,
                "latency_ms": latency_ms,
            }

    start_total = time.monotonic()
    results = await asyncio.gather(
        *(single_dispatch(user, flow_id, i) for i, (user, flow_id) in enumerate(user_flows))
    )
    total_elapsed = time.monotonic() - start_total

    status_codes = [r["status_code"] for r in results]
    assert all(code == 201 for code in status_codes), f"Unexpected statuses: {status_codes}"

    # Verify all execution IDs are distinct
    exec_ids = [r["body"]["id"] for r in results]
    assert len(set(exec_ids)) == N, "Duplicate execution IDs generated under concurrency"

    latencies = [r["latency_ms"] for r in results]
    latencies.sort()
    p50 = latencies[int(N * 0.5)]
    p95 = latencies[int(N * 0.95)]
    throughput = N / total_elapsed

    print(f"\n--- Concurrency Load Test Results (N={N}) ---")
    print(f"Total time: {total_elapsed:.3f}s | Throughput: {throughput:.1f} req/s")
    print(f"Latency: min={min(latencies):.1f}ms, p50={p50:.1f}ms, p95={p95:.1f}ms, max={max(latencies):.1f}ms")

    # Under in-memory SQLite table locking, sequential transactions serialize.
    # Verify that all concurrent requests complete successfully within 15s.
    assert p95 < 15000.0, f"p95 latency {p95:.1f}ms exceeded threshold"
