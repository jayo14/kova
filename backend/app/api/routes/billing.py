from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.modules.auth.dependencies import get_current_user
from app.modules.billing.schemas import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    InvoiceRead,
    PortalSessionRequest,
    PortalSessionResponse,
    SubscriptionRead,
)
from app.modules.billing.service import BillingService
from app.modules.organizations.repository import OrganizationRepository
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


async def _resolve_org(
    db: AsyncSession,
    user: User,
    org_id: Optional[uuid.UUID] = None,
    min_role: str = "member",
) -> uuid.UUID:
    org_repo = OrganizationRepository(db)
    if org_id:
        org = await org_repo.get_by_id(org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )
        if org.owner_user_id != user.id:
            member = await org_repo.get_member(org_id, user.id)
            if not member or (min_role in ("admin", "owner") and member.role not in ("admin", "owner")):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization administrative privileges required",
                )
        return org.id

    primary_org = await org_repo.get_user_primary_org(user.id)
    return primary_org.id


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(
    req: CheckoutSessionRequest,
    org_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create Stripe Checkout Session to upgrade subscription plan."""
    target_org_id = await _resolve_org(db, user, org_id, min_role="admin")
    service = BillingService(db)
    return await service.create_checkout(
        org_id=target_org_id,
        plan=req.plan,
        success_url=req.success_url,
        cancel_url=req.cancel_url,
        customer_email=user.email,
    )


@router.post("/portal", response_model=PortalSessionResponse)
async def create_portal(
    req: PortalSessionRequest,
    org_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Create Stripe Customer Portal Session for managing active subscriptions."""
    target_org_id = await _resolve_org(db, user, org_id, min_role="admin")
    service = BillingService(db)
    return await service.create_portal(
        org_id=target_org_id,
        return_url=req.return_url,
    )


@router.get("/subscription", response_model=SubscriptionRead)
async def get_subscription(
    org_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Get active subscription details for the organization."""
    target_org_id = await _resolve_org(db, user, org_id, min_role="member")
    service = BillingService(db)
    sub = await service.get_subscription(target_org_id)
    return SubscriptionRead.model_validate(sub)


@router.get("/invoices", response_model=list[InvoiceRead])
async def get_invoices(
    org_id: Optional[uuid.UUID] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """List billing invoices for the organization."""
    target_org_id = await _resolve_org(db, user, org_id, min_role="member")
    service = BillingService(db)
    return await service.get_invoices(target_org_id)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_session),
):
    """Handle Stripe incoming webhooks securely."""
    payload = await request.body()
    service = BillingService(db)
    try:
        return await service.handle_webhook(payload, stripe_signature)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to process Stripe webhook: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook error: {e}",
        )
