"""Unit tests for Billing, Stripe webhooks, Usage metering, and Plan limits."""

import uuid
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.billing.models import Invoice, Subscription, UsageEvent
from app.modules.billing.repository import BillingRepository
from app.modules.billing.service import BillingService
from app.modules.organizations.models import Organization, OrganizationQuota
from app.modules.organizations.repository import OrganizationRepository
from app.modules.users.models import User


@pytest.fixture
async def billing_user_and_org(db_session: AsyncSession):
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"billing-{user_id.hex[:6]}@example.com",
        name="Billing User",
    )
    db_session.add(user)
    await db_session.flush()

    org_repo = OrganizationRepository(db_session)
    org = await org_repo.create_organization(
        name=f"Billing Org {user_id.hex[:6]}",
        owner_user_id=user.id,
        plan="free",
    )
    return user, org


@pytest.mark.asyncio
async def test_stripe_webhook_creates_subscription(
    db_session: AsyncSession, billing_user_and_org
):
    _, org = billing_user_and_org
    service = BillingService(db_session)

    webhook_payload = {
        "id": "evt_test_checkout",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_12345",
                "client_reference_id": str(org.id),
                "customer": "cus_stripe_123",
                "subscription": "sub_stripe_pro_456",
                "metadata": {
                    "org_id": str(org.id),
                    "plan": "pro",
                },
            }
        },
    }

    res = await service.handle_webhook(webhook_payload, sig_header=None)
    assert res.get("received") is True

    # Assert subscription created
    sub = await service.repo.get_subscription_by_org_id(org.id)
    assert sub is not None
    assert sub.plan == "pro"
    assert sub.status == "active"
    assert sub.stripe_customer_id == "cus_stripe_123"
    assert sub.stripe_subscription_id == "sub_stripe_pro_456"

    # Assert organization quota updated for pro
    q_res = await db_session.execute(
        select(OrganizationQuota).where(OrganizationQuota.org_id == org.id)
    )
    quota = q_res.scalar_one_or_none()
    assert quota is not None
    assert quota.max_concurrent_executions == 5
    assert quota.max_executions_per_day == 500
    assert quota.max_evidence_storage_mb == 5000


@pytest.mark.asyncio
async def test_stripe_webhook_cancels_subscription(
    db_session: AsyncSession, billing_user_and_org
):
    _, org = billing_user_and_org
    service = BillingService(db_session)

    # First upgrade to pro
    await service.repo.upsert_subscription(
        org_id=org.id,
        plan="pro",
        status="active",
        stripe_customer_id="cus_stripe_123",
        stripe_subscription_id="sub_stripe_pro_456",
    )
    await service.update_org_quota_for_plan(org.id, "pro")
    await db_session.commit()

    # Now simulate customer.subscription.deleted
    webhook_payload = {
        "id": "evt_test_cancel",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_stripe_pro_456",
                "status": "canceled",
            }
        },
    }

    res = await service.handle_webhook(webhook_payload, sig_header=None)
    assert res.get("received") is True

    # Assert subscription status canceled and plan free
    sub = await service.repo.get_subscription_by_org_id(org.id)
    assert sub.status == "canceled"
    assert sub.plan == "free"

    # Assert quota downgraded back to free
    q_res = await db_session.execute(
        select(OrganizationQuota).where(OrganizationQuota.org_id == org.id)
    )
    quota = q_res.scalar_one_or_none()
    assert quota.max_concurrent_executions == 2
    assert quota.max_executions_per_day == 50
    assert quota.max_evidence_storage_mb == 100


@pytest.mark.asyncio
async def test_usage_metering(db_session: AsyncSession, billing_user_and_org):
    _, org = billing_user_and_org
    service = BillingService(db_session)

    # Initial usage should be 0
    summary = await service.get_usage_summary(org.id)
    assert summary.executions_this_month == 0
    assert summary.executions_limit == 50
    assert summary.executions_remaining == 50

    # Record 3 execution usage events
    await service.record_execution_usage(org.id, execution_id=None, storage_bytes=1024 * 1024 * 5)
    await service.record_execution_usage(org.id, execution_id=None, storage_bytes=1024 * 1024 * 10)
    await service.record_execution_usage(org.id, execution_id=None, storage_bytes=0)

    # Summary should now reflect the 3 executions and 15MB storage
    summary_after = await service.get_usage_summary(org.id)
    assert summary_after.executions_this_month == 3
    assert summary_after.executions_remaining == 47
    assert summary_after.evidence_storage_mb == 15.0


@pytest.mark.asyncio
async def test_plan_limit_enforcement(db_session: AsyncSession, billing_user_and_org):
    _, org = billing_user_and_org
    service = BillingService(db_session)

    # Org starts with 0 executions, should pass limit check
    await service.check_execution_limit(org.id)

    # Add 50 execution events
    for _ in range(50):
        await service.repo.record_usage_event(
            org_id=org.id,
            execution_id=None,
            plan_at_time="free",
        )
    await db_session.commit()

    # Now checking limit should raise 402 Payment Required
    with pytest.raises(HTTPException) as exc_info:
        await service.check_execution_limit(org.id)

    assert exc_info.value.status_code == 402
    assert "Monthly execution limit reached. Upgrade at" in exc_info.value.detail
    assert "/billing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_invoice_webhook_recording(db_session: AsyncSession, billing_user_and_org):
    _, org = billing_user_and_org
    service = BillingService(db_session)

    # Link subscription ID to org
    await service.repo.upsert_subscription(
        org_id=org.id,
        plan="pro",
        status="active",
        stripe_customer_id="cus_stripe_123",
        stripe_subscription_id="sub_test_inv_456",
    )
    await db_session.commit()

    payload = {
        "id": "evt_test_invoice",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_test_789",
                "subscription": "sub_test_inv_456",
                "amount_due": 4900,
                "amount_paid": 4900,
                "currency": "usd",
                "hosted_invoice_url": "https://stripe.com/invoices/in_test_789",
            }
        },
    }

    await service.handle_webhook(payload, sig_header=None)

    invoices = await service.get_invoices(org.id)
    assert len(invoices) >= 1
    inv = invoices[0]
    assert inv.stripe_invoice_id == "in_test_789"
    assert inv.amount_paid == 4900
    assert inv.status == "paid"
    assert inv.hosted_invoice_url == "https://stripe.com/invoices/in_test_789"
