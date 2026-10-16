"""Smoke test: Graceful system degradation when dependencies fail."""

import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.infrastructure.database.session import engine
from app.main import app
from app.engine.ai.settings import ai_settings
from app.engine.browser.evidence_storage import evidence_storage
from app.modules.executions.evidence_service import EvidenceService
from app.modules.flows.generator.ai_proposer import AIFlowProposer


@pytest.mark.asyncio
async def test_ai_provider_degradation(db_session: AsyncSession):
    """When AI APIs are unavailable or disabled, proposer falls back gracefully to deterministic logic."""
    proposer = AIFlowProposer(db_session)
    with patch.object(ai_settings, "AI_PROVIDER", "none"):
        proposals, ai_records = await proposer.propose(
            project_id=uuid.uuid4(),
            unresolved_goals=["Complete checkout"],
        )
        assert isinstance(proposals, list)
        assert len(proposals) == 0


@pytest.mark.asyncio
async def test_s3_storage_degradation(db_session: AsyncSession):
    """When S3 uploads fail, evidence collection catches error and degrades gracefully."""
    evidence_svc = EvidenceService(db_session)
    with patch.object(evidence_svc.event_service, "record_event", new_callable=AsyncMock):
        with patch.object(evidence_storage, "upload", side_effect=RuntimeError("S3 Connection Refused")):
            result = await evidence_svc.capture_screenshot(
                execution_id=uuid.uuid4(),
                screenshot_bytes=b"fake-bytes",
                title="Step Screenshot",
                purpose="step_evidence",
            )
            assert result is None


@pytest.mark.asyncio
async def test_postgres_readiness_degradation():
    """When database connectivity fails, GET /health/ready returns 503."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(type(engine), "connect", side_effect=Exception("Database connection failure")):
            res = await client.get("/health/ready")
            assert res.status_code == 503
            assert res.json()["detail"] == "Service dependencies unavailable"
