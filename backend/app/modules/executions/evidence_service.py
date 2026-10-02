"""Evidence service for capturing and managing execution proof."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.browser.evidence_storage import evidence_storage
from app.modules.executions.evidence_model import EvidenceStatus, EvidenceType
from app.modules.executions.evidence_repository import EvidenceRepository
from app.modules.executions.event_service import EventService

logger = logging.getLogger(__name__)


class EvidenceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EvidenceRepository(db)
        self.event_service = EventService(db)

    async def capture_screenshot(
        self,
        execution_id: uuid.UUID,
        screenshot_bytes: bytes,
        title: str,
        description: str | None = None,
        mime_type: str = "image/png",
    ) -> dict | None:
        """Capture a screenshot as evidence.

        Uploads to storage, persists evidence record, emits event.
        Returns evidence dict or None on failure.
        """
        evidence_id = uuid.uuid4()

        try:
            # Upload to storage
            upload_result = evidence_storage.upload(
                execution_id=str(execution_id),
                evidence_id=str(evidence_id),
                data=screenshot_bytes,
                content_type=mime_type,
            )

            # Persist evidence record
            evidence = await self.repo.create(
                execution_id=execution_id,
                type=EvidenceType.SCREENSHOT.value,
                title=title,
                description=description,
                status=EvidenceStatus.CAPTURED.value,
                storage_key=upload_result.get("storage_key"),
                mime_type=mime_type,
                metadata={"size_bytes": len(screenshot_bytes)},
            )

            # Emit event
            await self.event_service.record_event(
                execution_id,
                "evidence.captured",
                {
                    "evidence_id": str(evidence.id),
                    "type": EvidenceType.SCREENSHOT.value,
                    "title": title,
                },
            )

            logger.info(
                "Evidence captured: %s (execution=%s, type=%s)",
                evidence.id, execution_id, EvidenceType.SCREENSHOT.value,
            )

            return {
                "id": str(evidence.id),
                "execution_id": str(evidence.execution_id),
                "type": evidence.type,
                "title": evidence.title,
                "description": evidence.description,
                "status": evidence.status,
                "mime_type": evidence.mime_type,
                "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
            }

        except Exception as e:
            logger.warning("Evidence capture failed (execution=%s): %s", execution_id, e)
            await self.event_service.record_event(
                execution_id,
                "evidence.failed",
                {"type": EvidenceType.SCREENSHOT.value, "error": str(e)},
            )
            return None

    async def create_verification_evidence(
        self,
        execution_id: uuid.UUID,
        title: str,
        description: str,
        checks: list[dict] | None = None,
    ) -> dict | None:
        """Create verification evidence (structured proof that a check passed).

        No storage needed — this is metadata evidence.
        """
        try:
            evidence = await self.repo.create(
                execution_id=execution_id,
                type=EvidenceType.VERIFICATION.value,
                title=title,
                description=description,
                status=EvidenceStatus.VERIFIED.value,
                metadata={"checks": checks or []},
            )

            await self.event_service.record_event(
                execution_id,
                "evidence.captured",
                {
                    "evidence_id": str(evidence.id),
                    "type": EvidenceType.VERIFICATION.value,
                    "title": title,
                },
            )

            return {
                "id": str(evidence.id),
                "execution_id": str(evidence.execution_id),
                "type": evidence.type,
                "title": evidence.title,
                "description": evidence.description,
                "status": evidence.status,
                "metadata": evidence.extra_data,
                "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
            }

        except Exception as e:
            logger.warning("Verification evidence failed (execution=%s): %s", execution_id, e)
            return None

    async def get_evidence(self, evidence_id: uuid.UUID) -> dict | None:
        """Get evidence by ID."""
        evidence = await self.repo.get_by_id(evidence_id)
        if evidence is None:
            return None

        result = {
            "id": str(evidence.id),
            "execution_id": str(evidence.execution_id),
            "type": evidence.type,
            "title": evidence.title,
            "description": evidence.description,
            "status": evidence.status,
            "mime_type": evidence.mime_type,
            "storage_key": evidence.storage_key,
            "metadata": evidence.extra_data,
            "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
        }

        # Generate signed URL or local route for screenshot evidence
        if evidence.storage_key and evidence.type == EvidenceType.SCREENSHOT.value:
            signed_url = evidence_storage.create_signed_url(
                evidence.storage_key, str(evidence.execution_id)
            )
            result["url"] = signed_url or f"/api/v1/executions/{evidence.execution_id}/evidence/{evidence.id}/file"

        return result

    async def get_evidence_list(self, execution_id: uuid.UUID) -> list[dict]:
        """List all evidence for an execution, with signed URLs for artifacts."""
        evidence_items = await self.repo.list_by_execution(execution_id)

        results = []
        for evidence in evidence_items:
            item = {
                "id": str(evidence.id),
                "execution_id": str(evidence.execution_id),
                "type": evidence.type,
                "title": evidence.title,
                "description": evidence.description,
                "status": evidence.status,
                "mime_type": evidence.mime_type,
                "storage_key": evidence.storage_key,
                "metadata": evidence.extra_data,
                "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
            }

            # Generate signed URL or local route for screenshot evidence
            if evidence.storage_key and evidence.type == EvidenceType.SCREENSHOT.value:
                signed_url = evidence_storage.create_signed_url(
                    evidence.storage_key, str(evidence.execution_id)
                )
                item["url"] = signed_url or f"/api/v1/executions/{evidence.execution_id}/evidence/{evidence.id}/file"

            results.append(item)

        return results

    async def get_evidence_url(self, evidence_id: uuid.UUID) -> str | None:
        """Get a fresh signed URL for evidence artifact access."""
        evidence = await self.repo.get_by_id(evidence_id)
        if evidence is None or evidence.storage_key is None:
            return None

        signed_url = evidence_storage.create_signed_url(
            evidence.storage_key, str(evidence.execution_id)
        )
        return signed_url or f"/api/v1/executions/{evidence.execution_id}/evidence/{evidence.id}/file"

    async def cleanup_execution(self, execution_id: uuid.UUID) -> int:
        """Delete all evidence (storage objects + DB records) for an execution.

        Returns number of evidence items cleaned up.
        """
        evidence_items = await self.repo.list_by_execution(execution_id, limit=1000)
        cleaned = 0
        for evidence in evidence_items:
            if evidence.storage_key:
                try:
                    evidence_storage.delete(evidence.storage_key)
                except Exception as e:
                    logger.debug("Storage delete failed for %s: %s", evidence.storage_key, e)
            cleaned += 1

        deleted = await self.repo.delete_by_execution(execution_id)
        logger.info("Cleaned up %d evidence items for execution %s", deleted, execution_id)
        return deleted
