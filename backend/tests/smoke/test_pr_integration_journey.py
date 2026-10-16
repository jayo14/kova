"""Smoke test: End-to-end pull request webhook to validation and PR comment journey."""

import hashlib
import hmac
import json
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import get_session
from app.main import app
from app.modules.integrations.models import Integration
from app.modules.integrations.orchestrator import format_pr_comment
from app.modules.integrations.repository import IntegrationRepository
from app.modules.organizations.repository import OrganizationRepository
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.validation.schemas import (
    FlowRef,
    FlowValidationResult,
    ImpactReport,
    ValidationReport,
    ValidationRequest,
)


@pytest.mark.asyncio
async def test_pr_integration_journey(db_session: AsyncSession):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    try:
        user_id = uuid.uuid4()
        user = User(id=user_id, email=f"pr-tester-{user_id.hex[:6]}@example.com", name="PR Tester")
        db_session.add(user)
        await db_session.flush()

        org_repo = OrganizationRepository(db_session)
        org = await org_repo.create_organization(
            name=f"PR Org {user_id.hex[:6]}",
            owner_user_id=user.id,
            plan="pro",
        )

        project = Project(
            id=uuid.uuid4(),
            user_id=user.id,
            org_id=org.id,
            name="PR Demo Project",
            base_url="https://example.com",
        )
        db_session.add(project)
        await db_session.commit()

        # 1. Register GitHub Integration
        int_repo = IntegrationRepository(db_session)
        secret = "test-webhook-secret-1234"
        integration = await int_repo.create(
            project_id=project.id,
            provider="github",
            provider_repo_id="kova-ai/sample-app",
            webhook_secret=secret,
        )

        # 2. Simulate GitHub Pull Request Webhook
        payload = {
            "action": "opened",
            "repository": {"full_name": "kova-ai/sample-app"},
            "pull_request": {
                "number": 101,
                "head": {"sha": "c0ffee1234", "ref": "feat/payment-form"},
                "base": {"ref": "main"},
                "title": "Add Stripe payment form",
            },
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            webhook_res = await client.post(
                "/api/v1/integrations/github/webhook",
                content=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                    "X-GitHub-Event": "pull_request",
                },
            )
            assert webhook_res.status_code in (200, 202)

        # 3. Verify PR comment formatting output
        req = ValidationRequest(
            project_id=project.id,
            base_url=project.base_url,
        )
        dummy_report = ValidationReport(
            request=req,
            overall_status="passed",
            impact_report=ImpactReport(
                reason="Direct code modification to checkout form",
                direct_affected_flows=[FlowRef(id=str(uuid.uuid4()), name="Checkout Flow")],
                downstream_affected_flows=[],
                total_affected_flows=1,
            ),
            results=[
                FlowValidationResult(
                    flow_id=uuid.uuid4(),
                    flow_name="Checkout Flow",
                    role="target",
                    status="passed",
                    duration_ms=1250,
                )
            ],
            duration_ms=1300,
        )
        comment = format_pr_comment(
            report=dummy_report,
            event_id=uuid.uuid4(),
            project_id=project.id,
        )
        assert "## Kova Validation" in comment
        assert "passed" in comment
        assert "Checkout Flow" in comment
    finally:
        app.dependency_overrides.clear()
