"""Smoke test: End-to-end Stripe billing, upgrade, and downgrade lifecycle."""

import json
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.main import app
from app.modules.billing.repository import BillingRepository
from app.modules.billing.service import BillingService
from app.modules.organizations.repository import OrganizationRepository
from app.modules.users.models import User


@pytest.mark.asyncio
async def test_billing_journey(db_session: AsyncSession):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=f"billing-smoke-{user_id.hex[:6]}@kova.dev",
            name="Billing Smoke Tester",
        )
        db_session.add(user)
        await db_session.flush()

        org_repo = OrganizationRepository(db_session)
        org = await org_repo.create_organization(
            name=f"Billing Smoke Org {user_id.hex[:6]}",
            owner_user_id=user.id,
            plan="free",
        )
        await db_session.commit()

        service = BillingService(db_session)

        # 1. Free plan quota initially
        quota_free = await org_repo.get_quota(org.id)
        assert quota_free is not None
        assert quota_free.max_executions_per_day == 50
        assert quota_free.max_evidence_storage_mb == 100

        # 2. Simulate Stripe Checkout Completed -> Upgrade to Pro
        checkout_webhook = {
            "id": "evt_smoke_upgrade",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(org.id),
                    "customer": f"cus_smoke_{org.id.hex[:8]}",
                    "subscription": f"sub_smoke_pro_{org.id.hex[:8]}",
                    "metadata": {
                        "org_id": str(org.id),
                        "plan": "pro",
                    },
                }
            },
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            wh_res = await client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(checkout_webhook),
                headers={"Content-Type": "application/json"},
            )
            assert wh_res.status_code == 200

        # 3. Assert upgraded
        sub = await service.repo.get_subscription_by_org_id(org.id)
        assert sub is not None
        assert sub.plan == "pro"
        assert sub.status == "active"

        quota_pro = await org_repo.get_quota(org.id)
        assert quota_pro.max_executions_per_day == 500
        assert quota_pro.max_evidence_storage_mb == 5000

        # 4. Record execution usage
        await service.record_execution_usage(org.id, execution_id=None, storage_bytes=1024 * 1024 * 2)
        summary = await service.get_usage_summary(org.id)
        assert summary.executions_this_month == 1
        assert summary.executions_limit == 500
        assert summary.executions_remaining == 499

        # 5. Simulate Subscription Deleted -> Downgrade to Free
        cancel_webhook = {
            "id": "evt_smoke_cancel",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": f"sub_smoke_pro_{org.id.hex[:8]}",
                    "status": "canceled",
                }
            },
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            wh_cancel = await client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(cancel_webhook),
                headers={"Content-Type": "application/json"},
            )
            assert wh_cancel.status_code == 200

        # 6. Assert downgraded
        sub_cancelled = await service.repo.get_subscription_by_org_id(org.id)
        assert sub_cancelled.status_code == "canceled" if hasattr(sub_cancelled, "status_code") else sub_cancelled.status == "canceled"
        assert sub_cancelled.plan == "free"

        quota_downgraded = await org_repo.get_quota(org.id)
        assert quota_downgraded.max_executions_per_day == 50
    finally:
        app.dependency_overrides.clear()
