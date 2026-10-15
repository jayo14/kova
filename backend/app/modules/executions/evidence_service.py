"""Evidence service for capturing and managing execution proof."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.browser.evidence_storage import evidence_storage
from app.modules.executions.evidence_model import Evidence, EvidenceStatus, EvidenceType
from app.modules.executions.evidence_repository import EvidenceRepository
from app.modules.executions.event_service import EventService
from app.modules.executions.reporting import sanitize_payload, sanitize_text

logger = logging.getLogger(__name__)


class EvidenceService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = EvidenceRepository(db)
        self.event_service = EventService(db)

    async def create(
        self,
        execution_id: uuid.UUID,
        type: str,
        title: str,
        purpose: str | None = None,
        step_id: str | None = None,
        description: str | None = None,
        status: str = "CAPTURED",
        storage_key: str | None = None,
        mime_type: str | None = None,
        metadata: dict | None = None,
        dom_snapshot: str | None = None,
        a11y_tree: str | None = None,
        network_log: list | dict | None = None,
        video_url: str | None = None,
        trace_url: str | None = None,
        element_locator: str | None = None,
        timestamp_range: list | None = None,
        note: str | None = None,
    ) -> Evidence:
        """Create an evidence record with purpose and step_id enforcement.

        Rejects rows missing both purpose and step_id with ValueError (fail-closed).
        """
        if not purpose and not step_id:
            raise ValueError("Evidence must specify at least purpose or step_id")
        valid_purposes = {"verification", "failure", "step_evidence", "discovery", "legacy"}
        if purpose and purpose not in valid_purposes:
            raise ValueError(f"Invalid evidence purpose '{purpose}'. Must be one of {valid_purposes}")

        resolved_purpose = purpose or "step_evidence"
        return await self.repo.create(
            execution_id=execution_id,
            type=type,
            title=title,
            purpose=resolved_purpose,
            step_id=step_id,
            description=description,
            status=status,
            storage_key=storage_key,
            mime_type=mime_type,
            metadata=metadata or {},
            dom_snapshot=dom_snapshot,
            a11y_tree=a11y_tree,
            network_log=network_log,
            video_url=video_url,
            trace_url=trace_url,
            element_locator=element_locator,
            timestamp_range=timestamp_range,
            note=note,
        )

    async def capture_screenshot(
        self,
        execution_id: uuid.UUID,
        screenshot_bytes: bytes,
        title: str,
        purpose: str | None = None,
        step_id: str | None = None,
        description: str | None = None,
        mime_type: str = "image/png",
        extra_data: dict | None = None,
        dom_snapshot: str | None = None,
        a11y_tree: str | None = None,
        network_log: list | dict | None = None,
        video_url: str | None = None,
        trace_url: str | None = None,
        element_locator: str | None = None,
        timestamp_range: list | None = None,
        note: str | None = None,
    ) -> dict | None:
        """Capture a screenshot as evidence.

        Uploads to storage, persists evidence record, emits event.
        Returns evidence dict or None on failure.
        """
        evidence_id = uuid.uuid4()
        eff_purpose = purpose or (extra_data or {}).get("purpose") or (extra_data or {}).get("checkpoint")
        eff_step_id = step_id or (extra_data or {}).get("step_id")
        if not eff_purpose and not eff_step_id:
            raise ValueError("Evidence screenshot must declare purpose or step_id")

        valid_purposes = {"verification", "failure", "step_evidence", "discovery", "legacy"}
        if eff_purpose and eff_purpose not in valid_purposes:
            raise ValueError(f"Invalid evidence purpose '{eff_purpose}'. Must be one of {valid_purposes}")
        resolved_purpose = eff_purpose or "step_evidence"

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
                title=sanitize_text(title, limit=500),
                purpose=resolved_purpose,
                step_id=eff_step_id,
                description=sanitize_text(description) if description else None,
                status=EvidenceStatus.CAPTURED.value,
                storage_key=upload_result.get("storage_key"),
                mime_type=mime_type,
                metadata=sanitize_payload({"size_bytes": len(screenshot_bytes), **(extra_data or {})}),
                dom_snapshot=dom_snapshot,
                a11y_tree=a11y_tree,
                network_log=network_log,
                video_url=video_url,
                trace_url=trace_url,
                element_locator=element_locator,
                timestamp_range=timestamp_range,
                note=note,
            )

            # Emit event
            await self.event_service.record_event(
                execution_id,
                "evidence.captured",
                {
                    "evidence_id": str(evidence.id),
                    "type": EvidenceType.SCREENSHOT.value,
                    "title": title,
                    "purpose": resolved_purpose,
                    "step_id": eff_step_id,
                    **{key: value for key, value in (extra_data or {}).items() if key in {"step_id", "step_index", "checkpoint"}},
                },
            )

            logger.info(
                "Evidence captured: %s (execution=%s, type=%s, purpose=%s)",
                evidence.id, execution_id, EvidenceType.SCREENSHOT.value, resolved_purpose,
            )

            return {
                "id": str(evidence.id),
                "execution_id": str(evidence.execution_id),
                "type": evidence.type,
                "title": evidence.title,
                "purpose": evidence.purpose,
                "step_id": evidence.step_id,
                "description": evidence.description,
                "status": evidence.status,
                "mime_type": evidence.mime_type,
                "dom_snapshot": evidence.dom_snapshot,
                "a11y_tree": evidence.a11y_tree,
                "network_log": evidence.network_log,
                "video_url": evidence.video_url,
                "trace_url": evidence.trace_url,
                "element_locator": evidence.element_locator,
                "timestamp_range": evidence.timestamp_range,
                "note": evidence.note,
                "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
            }

        except ValueError:
            raise
        except Exception as e:
            logger.warning("Evidence capture failed (execution=%s, error_type=%s)", execution_id, type(e).__name__)
            await self.event_service.record_event(
                execution_id,
                "evidence.failed",
                {"type": EvidenceType.SCREENSHOT.value, "error": "Private evidence storage failed"},
            )
            return None

    async def create_verification_evidence(
        self,
        execution_id: uuid.UUID,
        title: str,
        description: str,
        purpose: str = "verification",
        step_id: str | None = None,
        checks: list[dict] | None = None,
        extra_data: dict | None = None,
        dom_snapshot: str | None = None,
        a11y_tree: str | None = None,
        network_log: list | dict | None = None,
        video_url: str | None = None,
        trace_url: str | None = None,
        element_locator: str | None = None,
        timestamp_range: list | None = None,
        note: str | None = None,
        storage_key: str | None = None,
        mime_type: str | None = None,
    ) -> dict | None:
        """Create verification evidence (structured proof that a check passed)."""
        eff_step_id = step_id or (extra_data or {}).get("step_id")
        try:
            evidence = await self.repo.create(
                execution_id=execution_id,
                type=EvidenceType.VERIFICATION.value,
                title=sanitize_text(title, limit=500),
                purpose=purpose,
                step_id=eff_step_id,
                description=sanitize_text(description),
                status=(
                    EvidenceStatus.VERIFIED.value
                    if checks and all(check.get("passed") is True for check in checks)
                    else EvidenceStatus.FAILED.value
                ),
                storage_key=storage_key,
                mime_type=mime_type,
                metadata=sanitize_payload({"checks": checks or [], **(extra_data or {})}),
                dom_snapshot=dom_snapshot,
                a11y_tree=a11y_tree,
                network_log=network_log,
                video_url=video_url,
                trace_url=trace_url,
                element_locator=element_locator,
                timestamp_range=timestamp_range,
                note=note,
            )

            await self.event_service.record_event(
                execution_id,
                "evidence.captured",
                {
                    "evidence_id": str(evidence.id),
                    "type": EvidenceType.VERIFICATION.value,
                    "title": title,
                    "purpose": purpose,
                    "step_id": eff_step_id,
                },
            )

            return {
                "id": str(evidence.id),
                "execution_id": str(evidence.execution_id),
                "type": evidence.type,
                "title": evidence.title,
                "purpose": evidence.purpose,
                "step_id": evidence.step_id,
                "description": evidence.description,
                "status": evidence.status,
                "dom_snapshot": evidence.dom_snapshot,
                "a11y_tree": evidence.a11y_tree,
                "network_log": evidence.network_log,
                "video_url": evidence.video_url,
                "trace_url": evidence.trace_url,
                "element_locator": evidence.element_locator,
                "timestamp_range": evidence.timestamp_range,
                "note": evidence.note,
                "metadata": evidence.extra_data,
                "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
            }

        except Exception as e:
            logger.warning("Verification evidence failed (execution=%s): %s", execution_id, e)
            return None

    async def link_evidence_to_step(self, evidence_id: uuid.UUID, step_id: str) -> None:
        """Link an existing evidence artifact to a specific step ID."""
        evidence = await self.repo.get_by_id(evidence_id)
        if evidence:
            evidence.step_id = step_id
            await self.db.commit()

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
            "purpose": evidence.purpose,
            "step_id": evidence.step_id,
            "description": evidence.description,
            "status": evidence.status,
            "mime_type": evidence.mime_type,
            "storage_key": evidence.storage_key,
            "dom_snapshot": evidence.dom_snapshot,
            "a11y_tree": evidence.a11y_tree,
            "network_log": evidence.network_log,
            "video_url": evidence.video_url,
            "trace_url": evidence.trace_url,
            "element_locator": evidence.element_locator,
            "timestamp_range": evidence.timestamp_range,
            "note": evidence.note,
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
                "purpose": evidence.purpose,
                "step_id": evidence.step_id,
                "description": evidence.description,
                "status": evidence.status,
                "mime_type": evidence.mime_type,
                "storage_key": evidence.storage_key,
                "dom_snapshot": evidence.dom_snapshot,
                "a11y_tree": evidence.a11y_tree,
                "network_log": evidence.network_log,
                "video_url": evidence.video_url,
                "trace_url": evidence.trace_url,
                "element_locator": evidence.element_locator,
                "timestamp_range": evidence.timestamp_range,
                "note": evidence.note,
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

    async def get_evidence_list_grouped_by_step(self, execution_id: uuid.UUID) -> list[dict]:
        """List evidence grouped by step_id in step appearance order."""
        items = await self.get_evidence_list(execution_id)
        grouped_dict: dict[str, list[dict]] = {}
        for item in items:
            sid = item.get("step_id") or "general"
            if sid not in grouped_dict:
                grouped_dict[sid] = []
            grouped_dict[sid].append(item)
        return [{"step_id": sid, "items": group_items} for sid, group_items in grouped_dict.items()]

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

    async def attach_execution_artifacts(
        self,
        execution_id: uuid.UUID,
        video_url: str | None = None,
        trace_url: str | None = None,
    ) -> int:
        """Attach video and/or trace URLs to all evidence records of an execution."""
        return await self.repo.attach_execution_artifacts(
            execution_id, video_url=video_url, trace_url=trace_url
        )

    async def get_for_validation(self, validation_id: uuid.UUID) -> list[Evidence]:
        """Return all evidence across all flows and executions in the validation."""
        import sqlalchemy as sa
        from app.modules.validation.models import ValidationReportModel, ValidationRun

        evidence_ids: list[uuid.UUID] = []
        execution_ids: list[uuid.UUID] = []

        stmt = sa.select(ValidationReportModel).where(ValidationReportModel.id == validation_id)
        res = await self.db.execute(stmt)
        vreport = res.scalars().first()
        if vreport and vreport.results:
            for r in vreport.results:
                evs = r.get("evidence_ids", []) if isinstance(r, dict) else getattr(r, "evidence_ids", [])
                for eid in evs:
                    try:
                        evidence_ids.append(uuid.UUID(str(eid)))
                    except Exception:
                        pass

        stmt_run = sa.select(ValidationRun).where(ValidationRun.id == validation_id)
        res_run = await self.db.execute(stmt_run)
        vrun = res_run.scalars().first()
        if vrun and vrun.execution_ids:
            for xid in vrun.execution_ids:
                try:
                    execution_ids.append(uuid.UUID(str(xid)))
                except Exception:
                    pass

        conditions = []
        if evidence_ids:
            conditions.append(Evidence.id.in_(evidence_ids))
        if execution_ids:
            conditions.append(Evidence.execution_id.in_(execution_ids))

        if not conditions:
            return []

        stmt_ev = sa.select(Evidence).where(sa.or_(*conditions)).order_by(Evidence.created_at.asc())
        ev_res = await self.db.execute(stmt_ev)
        return list(ev_res.scalars().all())
