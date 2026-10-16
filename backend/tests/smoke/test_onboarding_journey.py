"""Smoke test: End-to-end customer onboarding journey."""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.main import app
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_onboarding_journey(db_session: AsyncSession):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            user_id_suffix = uuid.uuid4().hex[:6]
            email = f"onboarding-{user_id_suffix}@kova.dev"
            password = "SecurePassword123!"

            # 1. Register new user
            reg_res = await client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": password, "name": "Onboarding Tester"},
            )
            assert reg_res.status_code == 200
            token = reg_res.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # 2. Check initial profile and onboarding step
            me_res = await client.get("/api/v1/auth/me", headers=headers)
            assert me_res.status_code == 200
            assert me_res.json()["onboarding_step"] == 0

            # 3. Wizard Step 1: Connect web app (create project)
            proj_res = await client.post(
                "/api/v1/projects/",
                json={
                    "name": "Acme SaaS",
                    "base_url": "https://example.com",
                    "description": "Onboarding project",
                },
                headers=headers,
            )
            assert proj_res.status_code in (200, 201)
            project_id = proj_res.json()["id"]

            # Update step to 1
            await client.patch(
                "/api/v1/auth/me/onboarding",
                json={"step": 1},
                headers=headers,
            )

            # 4. Wizard Step 2: Configure credentials
            cred_res = await client.post(
                f"/api/v1/projects/{project_id}/credentials",
                json={
                    "name": "Staging Tester",
                    "persona": "admin",
                    "auth_strategy": "password_form",
                    "email": "tester@example.com",
                    "password": "SecretPassword!",
                },
                headers=headers,
            )
            assert cred_res.status_code in (200, 201)

            # Update step to 2
            await client.patch(
                "/api/v1/auth/me/onboarding",
                json={"step": 2},
                headers=headers,
            )

            # 5. Wizard Step 3: Advance through discovery to validation
            await client.patch(
                "/api/v1/auth/me/onboarding",
                json={"step": 3},
                headers=headers,
            )

            # 6. Wizard Step 4: Run validation
            val_res = await client.post(
                "/api/v1/ci/validate",
                json={
                    "project_id": project_id,
                    "scope": "targeted",
                    "commit_sha": "abc1234",
                    "branch": "main",
                },
                headers=headers,
            )
            assert val_res.status_code == 201
            vdata = val_res.json()
            assert "id" in vdata
            assert vdata["status"].lower() in ("pending", "running", "passed")

            # 7. Complete onboarding
            finish_res = await client.patch(
                "/api/v1/auth/me/onboarding",
                json={"step": 4},
                headers=headers,
            )
            assert finish_res.status_code == 200
            assert finish_res.json()["onboarding_step"] == 4
    finally:
        app.dependency_overrides.clear()
