"""Integration tests for Billing webhooks, checkout, usage limits, and token management."""

import json
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.config.settings import settings
from app.main import app
from app.modules.auth.dependencies import _get_jwt_secret
from app.modules.billing.repository import BillingRepository
from app.modules.billing.service import BillingService
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


@pytest.fixture(autouse=True)
def enable_dev_mocks(monkeypatch):
    monkeypatch.setattr(settings, "DEV_ALLOW_MOCKS", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")


@pytest.mark.asyncio
async def test_end_to_end_billing_and_limits(db_session: AsyncSession):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        # 1. Create user and organization
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=f"e2e-billing-{user_id.hex[:6]}@example.com",
            name="E2E Billing User",
        )
        db_session.add(user)
        await db_session.flush()

        org_repo = OrganizationRepository(db_session)
        org = await org_repo.create_organization(
            name=f"E2E Org {user_id.hex[:6]}",
            owner_user_id=user.id,
            plan="free",
        )
        headers = _make_auth_header(user)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 2. Checkout endpoint
            checkout_res = await client.post(
                "/api/v1/billing/checkout",
                json={"plan": "pro"},
                headers=headers,
            )
            assert checkout_res.status_code == 200
            checkout_data = checkout_res.json()
            assert "checkout_url" in checkout_data
            assert "session_id" in checkout_data

            # 3. Customer portal endpoint
            portal_res = await client.post(
                "/api/v1/billing/portal",
                json={"return_url": "http://localhost:3000/billing"},
                headers=headers,
            )
            assert portal_res.status_code == 200
            portal_data = portal_res.json()
            assert "portal_url" in portal_data

            # 4. Simulate Stripe Webhook: checkout.session.completed
            webhook_payload = {
                "id": "evt_test_e2e_checkout",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "client_reference_id": str(org.id),
                        "customer": "cus_e2e_stripe",
                        "subscription": "sub_e2e_stripe_pro",
                        "metadata": {
                            "org_id": str(org.id),
                            "plan": "pro",
                        },
                    }
                },
            }
            webhook_res = await client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(webhook_payload),
                headers={"Content-Type": "application/json"},
            )
            assert webhook_res.status_code == 200

            # 5. Verify subscription upgraded
            sub_res = await client.get("/api/v1/billing/subscription", headers=headers)
            assert sub_res.status_code == 200
            sub_data = sub_res.json()
            assert sub_data["plan"] == "pro"
            assert sub_data["status"] == "active"

            # 6. Usage summary
            usage_res = await client.get("/api/v1/usage", headers=headers)
            assert usage_res.status_code == 200
            usage_data = usage_res.json()
            assert usage_data["plan"] == "pro"
            assert usage_data["executions_limit"] == 500

            # 7. Simulate cancellation webhook -> downgraded back to free
            cancel_payload = {
                "id": "evt_test_e2e_cancel",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_e2e_stripe_pro",
                        "status": "canceled",
                    }
                },
            }
            cancel_res = await client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(cancel_payload),
                headers={"Content-Type": "application/json"},
            )
            assert cancel_res.status_code == 200

            # Verify downgraded
            usage_downgraded = await client.get("/api/v1/usage", headers=headers)
            assert usage_downgraded.json()["plan"] == "free"
            assert usage_downgraded.json()["executions_limit"] == 50

            # 8. Token management testing
            # Create token
            tok_create_res = await client.post(
                "/api/v1/auth/tokens",
                json={"name": "CI Token", "scopes": ["ci:validate"]},
                headers=headers,
            )
            assert tok_create_res.status_code == 201
            tok_data = tok_create_res.json()
            raw_tok = tok_data["token"]
            assert raw_tok is not None
            assert raw_tok.startswith("kova_tok_")
            assert tok_data["scopes"] == ["ci:validate"]

            # List tokens (should NOT contain raw token)
            tok_list_res = await client.get("/api/v1/auth/tokens", headers=headers)
            assert tok_list_res.status_code == 200
            list_items = tok_list_res.json()
            assert len(list_items) >= 1
            assert list_items[0]["token"] is None

            # 9. Test 402 Monthly Limit Enforcement on CI validate
            # Create a test project for this org
            project = Project(
                id=uuid.uuid4(),
                org_id=org.id,
                name="Test E2E Project",
                base_url="https://example.com",
                user_id=user.id,
            )
            db_session.add(project)

            # Record 50 usage events
            billing_repo = BillingRepository(db_session)
            for _ in range(50):
                await billing_repo.record_usage_event(
                    org_id=org.id,
                    execution_id=None,
                    plan_at_time="free",
                )
            await db_session.commit()

            # CI validate with the created API token
            ci_res = await client.post(
                "/api/v1/ci/validate",
                json={"project_id": str(project.id)},
                headers={"Authorization": f"Bearer {raw_tok}"},
            )
            assert ci_res.status_code == 402
            assert "Monthly execution limit reached. Upgrade at" in ci_res.json()["detail"]

            # 10. Delete token
            del_res = await client.delete(
                f"/api/v1/auth/tokens/{tok_data['id']}",
                headers=headers,
            )
            assert del_res.status_code == 204
    finally:
        app.dependency_overrides.clear()
