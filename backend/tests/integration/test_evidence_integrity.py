"""Integration tests for evidence integrity and purpose/step_id enforcement."""
import uuid
import pytest
from sqlalchemy import select

from app.modules.executions.evidence_model import Evidence, EvidenceType, EvidenceStatus
from app.modules.executions.evidence_repository import EvidenceRepository
from app.modules.executions.evidence_service import EvidenceService
from app.modules.projects.repository import ProjectRepository
from app.modules.flows.repository import FlowRepository
from app.modules.executions.repository import ExecutionRepository


@pytest.fixture
async def project(db_session):
    repo = ProjectRepository(db_session)
    return await repo.create(name="EvidenceTestProject", base_url="http://localhost:3000")


@pytest.fixture
async def flow(db_session, project):
    repo = FlowRepository(db_session)
    return await repo.create(
        project_id=project.id,
        name="EvidenceFlow",
        steps=[{"action": "navigate", "value": "http://localhost:3000"}],
    )


@pytest.fixture
async def execution(db_session, flow):
    repo = ExecutionRepository(db_session)
    return await repo.create(flow_id=flow.id)


@pytest.mark.asyncio
async def test_evidence_service_create_rejects_orphan(db_session, execution):
    service = EvidenceService(db_session)
    with pytest.raises(ValueError, match="Evidence must specify at least purpose or step_id"):
        await service.create(
            execution_id=execution.id,
            type=EvidenceType.SCREENSHOT.value,
            title="Orphan screenshot without purpose or step_id",
            purpose=None,
            step_id=None,
        )


@pytest.mark.asyncio
async def test_evidence_roundtrip_with_purpose_and_step_id(db_session, execution):
    service = EvidenceService(db_session)
    repo = EvidenceRepository(db_session)

    # 1. Verification evidence
    v_ev = await service.create(
        execution_id=execution.id,
        type=EvidenceType.VERIFICATION.value,
        title="Verified checkout",
        purpose="verification",
        step_id="step_checkout_01",
        description="Checkout confirmation element visible",
    )
    assert v_ev.purpose == "verification"
    assert v_ev.step_id == "step_checkout_01"

    # 2. Step evidence screenshot
    s_ev = await service.create(
        execution_id=execution.id,
        type=EvidenceType.SCREENSHOT.value,
        title="Payment button clicked",
        purpose="step_evidence",
        step_id="step_payment_btn",
    )
    assert s_ev.purpose == "step_evidence"
    assert s_ev.step_id == "step_payment_btn"

    # 3. Query all evidence and verify no orphans exist
    all_evidence = await repo.list_by_execution(execution.id)
    assert len(all_evidence) == 2
    for item in all_evidence:
        assert item.purpose is not None and item.purpose != ""
        assert item.step_id is not None and item.step_id != ""

    # Check direct DB select
    stmt = select(Evidence).where(Evidence.execution_id == execution.id)
    res = await db_session.execute(stmt)
    rows = list(res.scalars().all())
    assert len(rows) == 2
    for row in rows:
        assert row.purpose in {"verification", "failure", "step_evidence", "discovery", "legacy"}
        assert row.step_id is not None
