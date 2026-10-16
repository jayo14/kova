from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import Invoice, Subscription, UsageEvent


class BillingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_subscription_by_org_id(self, org_id: uuid.UUID) -> Optional[Subscription]:
        stmt = select(Subscription).where(Subscription.org_id == org_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_subscription_by_stripe_subscription_id(
        self, stripe_sub_id: str
    ) -> Optional[Subscription]:
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_sub_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_subscription_by_customer_id(
        self, customer_id: str
    ) -> Optional[Subscription]:
        stmt = select(Subscription).where(
            Subscription.stripe_customer_id == customer_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_subscription(
        self,
        org_id: uuid.UUID,
        plan: str = "free",
        status: str = "active",
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None,
        current_period_start: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None,
    ) -> Subscription:
        sub = await self.get_subscription_by_org_id(org_id)
        if not sub:
            sub = Subscription(
                org_id=org_id,
                plan=plan,
                status=status,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
                current_period_start=current_period_start,
                current_period_end=current_period_end,
            )
            self.db.add(sub)
        else:
            sub.plan = plan
            sub.status = status
            if stripe_customer_id is not None:
                sub.stripe_customer_id = stripe_customer_id
            if stripe_subscription_id is not None:
                sub.stripe_subscription_id = stripe_subscription_id
            if current_period_start is not None:
                sub.current_period_start = current_period_start
            if current_period_end is not None:
                sub.current_period_end = current_period_end

        await self.db.flush()
        return sub

    async def record_invoice(
        self,
        org_id: uuid.UUID,
        stripe_invoice_id: str,
        amount_due: int = 0,
        amount_paid: int = 0,
        currency: str = "usd",
        status: str = "paid",
        hosted_invoice_url: Optional[str] = None,
    ) -> Invoice:
        stmt = select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice_id)
        res = await self.db.execute(stmt)
        inv = res.scalar_one_or_none()
        if not inv:
            inv = Invoice(
                org_id=org_id,
                stripe_invoice_id=stripe_invoice_id,
                amount_due=amount_due,
                amount_paid=amount_paid,
                currency=currency,
                status=status,
                hosted_invoice_url=hosted_invoice_url,
            )
            self.db.add(inv)
        else:
            inv.amount_due = amount_due
            inv.amount_paid = amount_paid
            inv.status = status
            if hosted_invoice_url:
                inv.hosted_invoice_url = hosted_invoice_url

        await self.db.flush()
        return inv

    async def get_invoices(
        self, org_id: uuid.UUID, limit: int = 50
    ) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .where(Invoice.org_id == org_id)
            .order_by(Invoice.created_at.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def record_usage_event(
        self,
        org_id: uuid.UUID,
        execution_id: Optional[uuid.UUID] = None,
        plan_at_time: str = "free",
        storage_bytes: int = 0,
    ) -> UsageEvent:
        event = UsageEvent(
            org_id=org_id,
            execution_id=execution_id,
            plan_at_time=plan_at_time,
            storage_bytes=storage_bytes,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def count_executions_in_period(
        self,
        org_id: uuid.UUID,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        stmt = (
            select(func.count(UsageEvent.id))
            .where(
                UsageEvent.org_id == org_id,
                UsageEvent.timestamp >= start_time,
                UsageEvent.timestamp <= end_time,
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar() or 0

    async def get_total_storage_bytes(self, org_id: uuid.UUID) -> int:
        stmt = (
            select(func.coalesce(func.sum(UsageEvent.storage_bytes), 0))
            .where(UsageEvent.org_id == org_id)
        )
        res = await self.db.execute(stmt)
        return int(res.scalar() or 0)
