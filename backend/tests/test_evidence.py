"""Tests for evidence model, service, and API endpoints."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.executions.evidence_model import Evidence, EvidenceType, EvidenceStatus
from app.modules.executions.evidence_schemas import EvidenceRead, EvidenceDetailRead
from app.modules.executions.evidence_repository import EvidenceRepository
from app.modules.executions.evidence_service import EvidenceService


class TestEvidenceModel:
    """Test Evidence model fields and constraints."""

    def test_evidence_type_enum(self):
        assert EvidenceType.SCREENSHOT.value == "SCREENSHOT"
        assert EvidenceType.VERIFICATION.value == "VERIFICATION"
        assert EvidenceType.ARTIFACT.value == "ARTIFACT"

    def test_evidence_status_enum(self):
        assert EvidenceStatus.CAPTURED.value == "CAPTURED"
        assert EvidenceStatus.VERIFIED.value == "VERIFIED"
        assert EvidenceStatus.FAILED.value == "FAILED"

    def test_evidence_create_minimal(self):
        evidence = Evidence(
            execution_id=uuid.uuid4(),
            type=EvidenceType.SCREENSHOT.value,
            title="Test screenshot",
            status=EvidenceStatus.CAPTURED.value,
            extra_data={},
        )
        assert evidence.type == "SCREENSHOT"
        assert evidence.title == "Test screenshot"
        assert evidence.status == "CAPTURED"
        assert evidence.extra_data == {}
        assert evidence.description is None
        assert evidence.storage_key is None
        assert evidence.mime_type is None
        assert evidence.extra_data == {}

    def test_evidence_create_full(self):
        eid = uuid.uuid4()
        evidence = Evidence(
            execution_id=eid,
            type=EvidenceType.VERIFICATION.value,
            title="Dashboard verified",
            description="Welcome text was visible",
            status=EvidenceStatus.VERIFIED.value,
            storage_key="exec/123/evidence/abc.png",
            mime_type="image/png",
            extra_data={"checks": [{"type": "text_visible", "passed": True}]},
        )
        assert evidence.execution_id == eid
        assert evidence.type == "VERIFICATION"
        assert evidence.storage_key == "exec/123/evidence/abc.png"
        assert evidence.extra_data["checks"][0]["passed"] is True


class TestEvidenceSchemas:
    """Test Pydantic schemas for evidence serialization."""

    def test_evidence_read(self):
        data = {
            "id": uuid.uuid4(),
            "execution_id": uuid.uuid4(),
            "type": "SCREENSHOT",
            "title": "Test",
            "description": None,
            "status": "CAPTURED",
            "mime_type": "image/png",
            "metadata": {},
            "created_at": "2026-09-16T20:00:00Z",
        }
        schema = EvidenceRead(**data)
        assert schema.type == "SCREENSHOT"
        assert schema.title == "Test"

    def test_evidence_detail_read_with_url(self):
        data = {
            "id": uuid.uuid4(),
            "execution_id": uuid.uuid4(),
            "type": "SCREENSHOT",
            "title": "Test",
            "description": None,
            "status": "CAPTURED",
            "mime_type": "image/png",
            "metadata": {},
            "created_at": "2026-09-16T20:00:00Z",
            "url": "https://example.com/signed-url",
        }
        schema = EvidenceDetailRead(**data)
        assert schema.url == "https://example.com/signed-url"


class TestEvidenceRepository:
    """Test EvidenceRepository DB operations (mocked)."""

    @pytest.mark.asyncio
    async def test_create_evidence(self):
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        repo = EvidenceRepository(mock_db)
        evidence = await repo.create(
            execution_id=uuid.uuid4(),
            type="SCREENSHOT",
            title="Test screenshot",
            description="A test",
            status="CAPTURED",
            storage_key="test.png",
            mime_type="image/png",
            metadata={"size": 1024},
        )

        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
        assert evidence.type == "SCREENSHOT"
        assert evidence.title == "Test screenshot"
        assert evidence.storage_key == "test.png"

    @pytest.mark.asyncio
    async def test_list_by_execution(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [
            Evidence(id=uuid.uuid4(), execution_id=uuid.uuid4(), type="SCREENSHOT", title="S1", status="CAPTURED"),
            Evidence(id=uuid.uuid4(), execution_id=uuid.uuid4(), type="VERIFICATION", title="V1", status="VERIFIED"),
        ]
        mock_db.execute.return_value = mock_result

        repo = EvidenceRepository(mock_db)
        result = await repo.list_by_execution(uuid.uuid4())

        assert len(result) == 2
        mock_db.execute.assert_called_once()


class TestEvidenceService:
    """Test EvidenceService business logic (mocked storage + DB)."""

    @pytest.mark.asyncio
    async def test_capture_screenshot(self):
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.flush = AsyncMock()

        with patch("app.modules.executions.evidence_service.evidence_storage") as mock_storage, \
             patch("app.modules.executions.evidence_service.EvidenceRepository") as MockRepo:
            mock_storage.upload.return_value = {"storage_key": "exec/123/evidence/abc.png"}
            mock_repo = AsyncMock()
            mock_repo.create.return_value = Evidence(
                id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                type="SCREENSHOT",
                title="Verified state",
                storage_key="exec/123/evidence/abc.png",
            )
            MockRepo.return_value = mock_repo

            service = EvidenceService(mock_db)
            result = await service.capture_screenshot(
                execution_id=uuid.uuid4(),
                screenshot_bytes=b"fake-png-data",
                title="Verified browser state",
            )

            mock_storage.upload.assert_called_once()
            mock_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_verification_evidence(self):
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        with patch("app.modules.executions.evidence_service.EvidenceRepository") as MockRepo:
            mock_repo = AsyncMock()
            mock_repo.create.return_value = Evidence(
                id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                type="VERIFICATION",
                title="Verification passed",
                status="VERIFIED",
            )
            MockRepo.return_value = mock_repo

            service = EvidenceService(mock_db)
            result = await service.create_verification_evidence(
                execution_id=uuid.uuid4(),
                title="Verification passed",
                description="All checks passed",
                checks=[{"type": "text_visible", "passed": True, "message": "Found"}],
            )

            mock_repo.create.assert_called_once()
            call_kwargs = mock_repo.create.call_args[1]
            assert call_kwargs["type"] == "VERIFICATION"
            assert call_kwargs["status"] == "VERIFIED"
