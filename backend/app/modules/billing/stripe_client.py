"""Stripe API wrapper and checkout/portal session generator."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import HTTPException, status
import stripe

from app.config.settings import settings

logger = logging.getLogger(__name__)


class StripeClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.STRIPE_SECRET_KEY
        if self.api_key:
            stripe.api_key = self.api_key

    def is_configured(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("mock_"))

    async def create_checkout_session(
        self,
        org_id: uuid.UUID,
        plan: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> tuple[str, str]:
        """Create a Stripe Checkout Session for upgrading organization plan."""
        base_frontend = settings.FRONTEND_URL.rstrip("/")
        s_url = success_url or f"{base_frontend}/billing?session_id={{CHECKOUT_SESSION_ID}}&status=success"
        c_url = cancel_url or f"{base_frontend}/billing?status=cancelled"

        if not self.is_configured():
            if settings.allow_mocks:
                mock_id = f"cs_test_{uuid.uuid4().hex[:24]}"
                mock_url = f"{base_frontend}/billing?session_id={mock_id}&status=success"
                return mock_url, mock_id

            if settings.is_production:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Stripe is not configured in production (STRIPE_SECRET_KEY is missing)",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe is not configured. Enable DEV_ALLOW_MOCKS for local development mocking.",
            )

        price_id = (
            settings.STRIPE_ENTERPRISE_PRICE_ID
            if plan == "enterprise"
            else settings.STRIPE_PRO_PRICE_ID
        )

        params: dict[str, Any] = {
            "mode": "subscription",
            "payment_method_types": ["card"],
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": s_url,
            "cancel_url": c_url,
            "client_reference_id": str(org_id),
            "metadata": {
                "org_id": str(org_id),
                "plan": plan,
            },
        }
        if customer_id:
            params["customer"] = customer_id
        elif customer_email:
            params["customer_email"] = customer_email

        session = stripe.checkout.Session.create(**params)
        return session.url, session.id

    async def create_portal_session(
        self,
        org_id: uuid.UUID,
        customer_id: str,
        return_url: Optional[str] = None,
    ) -> str:
        """Create a Stripe Customer Portal Session for subscription management."""
        base_frontend = settings.FRONTEND_URL.rstrip("/")
        r_url = return_url or f"{base_frontend}/billing"

        if not self.is_configured():
            if settings.allow_mocks:
                return f"{base_frontend}/billing?portal=mock_active"
            if settings.is_production:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Stripe is not configured in production (STRIPE_SECRET_KEY is missing)",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Stripe is not configured. Enable DEV_ALLOW_MOCKS for local development mocking.",
            )

        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Stripe customer ID associated with this organization.",
            )

        if customer_id.startswith("cus_mock_"):
            if settings.allow_mocks:
                return f"{base_frontend}/billing?portal=mock_active"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mock customer IDs are not permitted.",
            )

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=r_url,
        )
        return session.url

    def construct_webhook_event(
        self,
        payload: bytes | str,
        sig_header: Optional[str],
        webhook_secret: Optional[str] = None,
    ) -> Any:
        """Verify and construct a Stripe webhook event from raw payload and signature."""
        secret = webhook_secret or settings.STRIPE_WEBHOOK_SECRET
        if not secret:
            if settings.is_production:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="STRIPE_WEBHOOK_SECRET is not configured in production",
                )
            if not settings.allow_mocks:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="STRIPE_WEBHOOK_SECRET is not configured",
                )
            import json
            return json.loads(payload) if isinstance(payload, (bytes, str)) else payload

        if not sig_header:
            if settings.allow_mocks and secret == "mock_secret":
                import json
                return json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe-Signature header",
            )

        if secret == "mock_secret":
            if not settings.allow_mocks:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mock webhook secret is only permitted when DEV_ALLOW_MOCKS is enabled in development",
                )
            import json
            return json.loads(payload) if isinstance(payload, (bytes, str)) else payload

        try:
            return stripe.Webhook.construct_event(
                payload=payload,
                sig_header=sig_header,
                secret=secret,
            )
        except stripe.error.SignatureVerificationError as e:
            logger.warning("Stripe webhook signature verification failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Stripe webhook signature: {e}",
            )
        except Exception as e:
            logger.error("Failed to construct Stripe webhook event: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Webhook event construction failed: {e}",
            )

    async def cancel_subscription(self, stripe_subscription_id: str) -> None:
        """Cancel a subscription at period end."""
        if not self.is_configured() or stripe_subscription_id.startswith("sub_mock_"):
            if settings.is_production:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Stripe is not configured in production",
                )
            if not settings.allow_mocks:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Stripe is not configured",
                )
            return
        stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=True)


stripe_client = StripeClient()
