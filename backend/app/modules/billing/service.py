from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.billing.models import Subscription
from app.modules.billing.repository import BillingRepository
from app.modules.billing.schemas import (
    CheckoutSessionResponse,
    InvoiceRead,
    PlanType,
    PortalSessionResponse,
    SubscriptionRead,
    UsageSummary,
)
from app.modules.billing.stripe_client import StripeClient
from app.modules.organizations.models import Organization, OrganizationQuota

logger = logging.getLogger(__name__)

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "executions_per_month": 50,
        "max_concurrent": 2,
        "max_daily": 50,
        "storage_mb": 100,
        "allowed_integrations": ["github"],
    },
    "pro": {
        "executions_per_month": 500,
        "max_concurrent": 5,
        "max_daily": 500,
        "storage_mb": 5000,
        "allowed_integrations": ["github", "gitlab", "jira", "slack"],
    },
    "enterprise": {
        "executions_per_month": 5000,
        "max_concurrent": 20,
        "max_daily": 5000,
        "storage_mb": 50000,
        "allowed_integrations": ["*"],
    },
}


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = BillingRepository(db)
        self.stripe_client = StripeClient()

    async def get_subscription(self, org_id: uuid.UUID) -> Subscription:
        sub = await self.repo.get_subscription_by_org_id(org_id)
        if not sub:
            # Query organization plan as baseline
            org_res = await self.db.execute(select(Organization).where(Organization.id == org_id))
            org = org_res.scalar_one_or_none()
            plan = org.plan if org else "free"
            sub = await self.repo.upsert_subscription(org_id=org_id, plan=plan, status="active")
            await self.db.commit()
            await self.db.refresh(sub)
        return sub

    async def create_checkout(
        self,
        org_id: uuid.UUID,
        plan: PlanType,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        customer_email: Optional[str] = None,
    ) -> CheckoutSessionResponse:
        sub = await self.get_subscription(org_id)
        url, session_id = await self.stripe_client.create_checkout_session(
            org_id=org_id,
            plan=plan,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            customer_id=sub.stripe_customer_id,
        )
        return CheckoutSessionResponse(checkout_url=url, session_id=session_id)

    async def create_portal(
        self,
        org_id: uuid.UUID,
        return_url: Optional[str] = None,
    ) -> PortalSessionResponse:
        sub = await self.get_subscription(org_id)
        customer_id = sub.stripe_customer_id or f"cus_mock_{org_id.hex[:12]}"
        portal_url = await self.stripe_client.create_portal_session(
            org_id=org_id,
            customer_id=customer_id,
            return_url=return_url,
        )
        return PortalSessionResponse(portal_url=portal_url)

    async def update_org_quota_for_plan(self, org_id: uuid.UUID, plan: str) -> None:
        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
        org_res = await self.db.execute(select(Organization).where(Organization.id == org_id))
        org = org_res.scalar_one_or_none()
        if org:
            org.plan = plan

        quota_res = await self.db.execute(
            select(OrganizationQuota).where(OrganizationQuota.org_id == org_id)
        )
        quota = quota_res.scalar_one_or_none()
        if not quota:
            quota = OrganizationQuota(
                org_id=org_id,
                max_concurrent_executions=limits["max_concurrent"],
                max_executions_per_day=limits["max_daily"],
                max_evidence_storage_mb=limits["storage_mb"],
                allowed_integrations=limits["allowed_integrations"],
            )
            self.db.add(quota)
        else:
            quota.max_concurrent_executions = limits["max_concurrent"]
            quota.max_executions_per_day = limits["max_daily"]
            quota.max_evidence_storage_mb = limits["storage_mb"]
            quota.allowed_integrations = limits["allowed_integrations"]

    async def handle_webhook(
        self, payload: bytes | str, sig_header: Optional[str]
    ) -> dict[str, Any]:
        event = self.stripe_client.construct_webhook_event(payload, sig_header)
        event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", "")
        data_object = (
            event.get("data", {}).get("object", {})
            if isinstance(event, dict)
            else getattr(getattr(event, "data", None), "object", {})
        )

        logger.info("Received Stripe webhook event: %s", event_type)

        if event_type == "checkout.session.completed":
            client_ref = data_object.get("client_reference_id")
            metadata = data_object.get("metadata", {}) or {}
            org_id_str = client_ref or metadata.get("org_id")
            plan = metadata.get("plan", "pro")
            customer_id = data_object.get("customer")
            subscription_id = data_object.get("subscription")

            if org_id_str:
                try:
                    org_id = uuid.UUID(org_id_str)
                    await self.repo.upsert_subscription(
                        org_id=org_id,
                        plan=plan,
                        status="active",
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=subscription_id,
                    )
                    await self.update_org_quota_for_plan(org_id, plan)
                    await self.db.commit()
                except Exception as e:
                    logger.error("Error processing checkout.session.completed: %s", e)

        elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
            sub_id = data_object.get("id")
            status_val = data_object.get("status", "active")
            period_start = data_object.get("current_period_start")
            period_end = data_object.get("current_period_end")

            dt_start = (
                datetime.fromtimestamp(period_start, tz=timezone.utc)
                if period_start
                else None
            )
            dt_end = (
                datetime.fromtimestamp(period_end, tz=timezone.utc)
                if period_end
                else None
            )

            existing = await self.repo.get_subscription_by_stripe_subscription_id(sub_id)
            if existing:
                existing.status = status_val
                if dt_start:
                    existing.current_period_start = dt_start
                if dt_end:
                    existing.current_period_end = dt_end
                await self.db.commit()

        elif event_type == "customer.subscription.deleted":
            sub_id = data_object.get("id")
            existing = await self.repo.get_subscription_by_stripe_subscription_id(sub_id)
            if existing:
                existing.status = "canceled"
                existing.plan = "free"
                await self.update_org_quota_for_plan(existing.org_id, "free")
                await self.db.commit()

        elif event_type == "invoice.paid":
            inv_id = data_object.get("id")
            sub_id = data_object.get("subscription")
            amount_paid = data_object.get("amount_paid", 0)
            amount_due = data_object.get("amount_due", 0)
            currency = data_object.get("currency", "usd")
            hosted_url = data_object.get("hosted_invoice_url")

            existing_sub = (
                await self.repo.get_subscription_by_stripe_subscription_id(sub_id)
                if sub_id
                else None
            )
            if existing_sub:
                await self.repo.record_invoice(
                    org_id=existing_sub.org_id,
                    stripe_invoice_id=inv_id,
                    amount_due=amount_due,
                    amount_paid=amount_paid,
                    currency=currency,
                    status="paid",
                    hosted_invoice_url=hosted_url,
                )
                await self.db.commit()

        elif event_type == "invoice.payment_failed":
            inv_id = data_object.get("id")
            sub_id = data_object.get("subscription")
            amount_due = data_object.get("amount_due", 0)
            currency = data_object.get("currency", "usd")
            hosted_url = data_object.get("hosted_invoice_url")

            existing_sub = (
                await self.repo.get_subscription_by_stripe_subscription_id(sub_id)
                if sub_id
                else None
            )
            if existing_sub:
                await self.repo.record_invoice(
                    org_id=existing_sub.org_id,
                    stripe_invoice_id=inv_id,
                    amount_due=amount_due,
                    amount_paid=0,
                    currency=currency,
                    status="open",
                    hosted_invoice_url=hosted_url,
                )
                existing_sub.status = "past_due"
                await self.db.commit()

        return {"received": True}

    async def get_usage_summary(self, org_id: uuid.UUID) -> UsageSummary:
        sub = await self.get_subscription(org_id)
        plan = sub.plan or "free"
        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

        now = datetime.now(timezone.utc)
        start_date = (
            sub.current_period_start
            if sub.current_period_start
            else datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        )
        # End date default to end of current month
        end_date = (
            sub.current_period_end
            if sub.current_period_end
            else datetime(now.year + (1 if now.month == 12 else 0), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
        )

        exec_count = await self.repo.count_executions_in_period(org_id, start_date, end_date)
        total_storage_bytes = await self.repo.get_total_storage_bytes(org_id)
        storage_mb = round(total_storage_bytes / (1024 * 1024), 2)

        exec_limit = limits["executions_per_month"]
        storage_limit = float(limits["storage_mb"])
        remaining = max(0, exec_limit - exec_count)

        return UsageSummary(
            executions_this_month=exec_count,
            executions_limit=exec_limit,
            executions_remaining=remaining,
            evidence_storage_mb=storage_mb,
            evidence_storage_limit_mb=storage_limit,
            plan=plan,
            period_start=start_date,
            period_end=end_date,
        )

    async def check_execution_limit(self, org_id: uuid.UUID) -> None:
        summary = await self.get_usage_summary(org_id)
        if summary.executions_this_month >= summary.executions_limit:
            billing_url = f"{settings.FRONTEND_URL.rstrip('/')}/billing"
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Monthly execution limit reached. Upgrade at {billing_url}.",
            )

    async def record_execution_usage(
        self,
        org_id: uuid.UUID,
        execution_id: Optional[uuid.UUID] = None,
        storage_bytes: int = 0,
    ) -> None:
        sub = await self.get_subscription(org_id)
        plan = sub.plan if sub else "free"
        await self.repo.record_usage_event(
            org_id=org_id,
            execution_id=execution_id,
            plan_at_time=plan,
            storage_bytes=storage_bytes,
        )
        await self.db.commit()

    async def get_invoices(self, org_id: uuid.UUID) -> list[InvoiceRead]:
        invoices = await self.repo.get_invoices(org_id)
        return [InvoiceRead.model_validate(inv) for inv in invoices]
