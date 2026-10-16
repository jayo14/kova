from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import AuditEvent

logger = logging.getLogger(__name__)

_REDACTION_PATTERNS = [
    re.compile(r"pass(word)?", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"key", re.IGNORECASE),
    re.compile(r"auth(orization)?", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
]


def redact_audit_metadata(data: Any) -> Any:
    """Recursively scrub any sensitive credentials, tokens, or secrets from audit logs."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            k_str = str(k)
            if any(p.search(k_str) for p in _REDACTION_PATTERNS):
                cleaned[k_str] = "***REDACTED***"
            else:
                cleaned[k_str] = redact_audit_metadata(v)
        return cleaned
    if isinstance(data, list):
        return [redact_audit_metadata(item) for item in data]
    return data


class AuditLogger:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        event_type: str,
        actor_user_id: Optional[uuid.UUID],
        org_id: uuid.UUID,
        project_id: Optional[uuid.UUID] = None,
        action: str = "",
        target: str = "",
        metadata: Optional[dict] = None,
    ) -> AuditEvent:
        """Persist a scrubbed audit record for mutating operations."""
        clean_metadata = redact_audit_metadata(metadata or {})
        event = AuditEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            actor_user_id=actor_user_id,
            project_id=project_id,
            event_type=event_type,
            action=action or event_type,
            target=target or "unknown",
            metadata_=clean_metadata,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        logger.info(
            "AuditEvent recorded: org=%s actor=%s type=%s action=%s target=%s",
            org_id,
            actor_user_id,
            event_type,
            action,
            target,
        )
        return event
