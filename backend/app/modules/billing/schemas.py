"""Pydantic schemas for Billing, Checkout, Invoices, and Usage metering."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


PlanType = Literal["free", "pro", "enterprise"]


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    plan: str
    status: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CheckoutSessionRequest(BaseModel):
    plan: PlanType
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalSessionRequest(BaseModel):
    return_url: Optional[str] = None


class PortalSessionResponse(BaseModel):
    portal_url: str


class UsageSummary(BaseModel):
    executions_this_month: int
    executions_limit: int
    executions_remaining: int
    evidence_storage_mb: float
    evidence_storage_limit_mb: float
    plan: str
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    stripe_invoice_id: str
    amount_due: int
    amount_paid: int
    currency: str
    status: str
    hosted_invoice_url: Optional[str] = None
    created_at: datetime
