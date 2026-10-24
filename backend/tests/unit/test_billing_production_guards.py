"""Tests for production billing and email guards, mock isolation, and readiness reporting."""

import uuid
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.config.settings import settings
from app.main import app
from app.modules.auth.dependencies import _get_jwt_secret
from app.modules.billing.service import BillingService
from app.modules.billing.stripe_client import StripeClient
from app.modules.email.service import EmailService
from app.modules.organizations.models import Organization
from app.modules.organizations.repository import OrganizationRepository
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
async def billing_setup(db_session: AsyncSession):
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"guard-test-{user_id.hex[:6]}@example.com",
        name="Guard User",
    )
    db_session.add(user)
    await db_session.flush()

    org_repo = OrganizationRepository(db_session)
    org = await org_repo.create_organization(
        name=f"Guard Org {user_id.hex[:6]}",
        owner_user_id=user.id,
        plan="free",
    )
    return user, org


@pytest.mark.asyncio
async def test_billing_actions_fail_in_production_without_stripe_key(
    db_session: AsyncSession, billing_setup, monkeypatch
):
    """In production with no Stripe key, checkout and portal sessions fail with 503."""
    user, org = billing_setup
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "DEV_ALLOW_MOCKS", False)

    service = BillingService(db_session)

    # create_checkout fails with 503 clear error
    with pytest.raises(HTTPException) as exc_info:
        await service.create_checkout(org.id, plan="pro")
    assert exc_info.value.status_code == 503
    assert "production" in exc_info.value.detail.lower()

    # create_portal fails with 503 clear error
    with pytest.raises(HTTPException) as exc_info:
        await service.create_portal(org.id)
    assert exc_info.value.status_code in (400, 503)


@pytest.mark.asyncio
async def test_billing_actions_fail_in_dev_when_mocks_not_enabled(
    db_session: AsyncSession, billing_setup, monkeypatch
):
    """In dev without DEV_ALLOW_MOCKS, checkout fails with 503 directing to flag."""
    user, org = billing_setup
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "DEV_ALLOW_MOCKS", False)

    service = BillingService(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_checkout(org.id, plan="pro")
    assert exc_info.value.status_code == 503
    assert "DEV_ALLOW_MOCKS" in exc_info.value.detail


@pytest.mark.asyncio
async def test_forged_success_url_does_not_change_plan(
    db_session: AsyncSession, billing_setup, monkeypatch
):
    """A client calling with forged success query params or fake IDs cannot alter org.plan."""
    user, org = billing_setup
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setattr(settings, "DEV_ALLOW_MOCKS", False)

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    headers = _make_auth_header(user)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Client tries calling subscription or other endpoints with forged parameters
        res = await client.get(
            f"/api/v1/billing/subscription?session_id=cs_forged_123&status=success&plan=enterprise",
            headers=headers,
        )
        assert res.status_code == 200
        sub_data = res.json()
        # Org plan remains free; client-supplied params have no effect
        assert sub_data["plan"] == "free"

        # Webhook without valid signature fails and changes nothing
        fake_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": str(org.id),
                    "customer": "cus_forged_123",
                    "metadata": {"org_id": str(org.id), "plan": "enterprise"},
                }
            },
        }
        webhook_res = await client.post(
            "/api/v1/billing/webhook",
            json=fake_payload,
            headers={"Stripe-Signature": "t=123,v1=forged_sig"},
        )
        assert webhook_res.status_code == 400

        # Plan in database is still free
        await db_session.refresh(org)
        assert org.plan == "free"


@pytest.mark.asyncio
async def test_mock_customer_id_rejected_in_webhook(
    db_session: AsyncSession, billing_setup, monkeypatch
):
    """Webhook rejects mock customer IDs (cus_mock_) when DEV_ALLOW_MOCKS is False."""
    user, org = billing_setup
    monkeypatch.setattr(settings, "DEV_ALLOW_MOCKS", False)

    service = BillingService(db_session)
    webhook_payload = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(org.id),
                "customer": f"cus_mock_{org.id.hex[:12]}",
                "metadata": {"org_id": str(org.id), "plan": "enterprise"},
            }
        },
    }

    # Bypassing signature directly at service level to test customer_id guard
    monkeypatch.setattr(
        service.stripe_client,
        "construct_webhook_event",
        lambda p, s: webhook_payload,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.handle_webhook(webhook_payload, sig_header=None)

    assert exc_info.value.status_code == 400
    assert "Mock customer IDs are not permitted" in exc_info.value.detail

    await db_session.refresh(org)
    assert org.plan == "free"


@pytest.mark.asyncio
async def test_readiness_reports_live_integrations(monkeypatch):
    """Readiness endpoint reports live integration status in development."""
    from app import main
    from app.workers.celery_app import celery_app

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement):
            return None

    class RedisClient:
        async def ping(self):
            return True

        async def aclose(self):
            return None

    class Inspector:
        def ping(self):
            return {"worker@test": {"ok": "pong"}}

    monkeypatch.setattr(type(main.engine), "connect", lambda self: Connection())
    monkeypatch.setattr(main.Redis, "from_url", lambda *args, **kwargs: RedisClient())
    monkeypatch.setattr(celery_app.control, "inspect", lambda *args, **kwargs: Inspector())

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health/ready")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert "integrations" in data
        assert data["integrations"]["stripe"] is False
        assert data["integrations"]["ses"] is False


@pytest.mark.asyncio
async def test_readiness_fails_in_production_when_integrations_missing(monkeypatch):
    """In production, readiness returns 503 if Stripe or SES credentials are missing."""
    from app import main
    from app.workers.celery_app import celery_app

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement):
            return None

    class RedisClient:
        async def ping(self):
            return True

        async def aclose(self):
            return None

    class Inspector:
        def ping(self):
            return {"worker@test": {"ok": "pong"}}

    monkeypatch.setattr(type(main.engine), "connect", lambda self: Connection())
    monkeypatch.setattr(main.Redis, "from_url", lambda *args, **kwargs: RedisClient())
    monkeypatch.setattr(celery_app.control, "inspect", lambda *args, **kwargs: Inspector())

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health/ready")
        assert res.status_code == 503
        data = res.json()
        assert "missing required integrations" in data["detail"].lower()
