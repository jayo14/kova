from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.crypto import encrypt_credential, decrypt_credential
from app.modules.integrations.models import Integration, IntegrationEvent


_SENSITIVE_KEYS = {"password", "passwd", "token", "secret", "authorization", "cookie", "api_key", "access_key", "key"}


def redact_webhook_payload(payload: Any) -> Any:
    """Walk payload and redact any sensitive token/secret/password/key values."""
    if isinstance(payload, dict):
        cleaned = {}
        for k, v in payload.items():
            k_lower = str(k).lower().replace("-", "_")
            if any(re.search(pattern, k_lower) for pattern in [r"token", r"secret", r"password", r"key", r"credential"]):
                cleaned[k] = "***REDACTED***"
            else:
                cleaned[k] = redact_webhook_payload(v)
        return cleaned
    if isinstance(payload, list):
        return [redact_webhook_payload(item) for item in payload]
    return payload


class IntegrationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        project_id: uuid.UUID,
        provider: str,
        provider_repo_id: str,
        webhook_secret: str,
        access_token: str | None = None,
        provider_installation_id: str | None = None,
        default_branch: str = "main",
        kova_config_path: str = ".kova.yml",
    ) -> Integration:
        encrypted_secret = encrypt_credential(webhook_secret)
        encrypted_token = encrypt_credential(access_token) if access_token else None

        integration = Integration(
            id=uuid.uuid4(),
            project_id=project_id,
            provider=provider,
            provider_repo_id=provider_repo_id,
            provider_installation_id=provider_installation_id,
            webhook_secret=encrypted_secret,
            access_token=encrypted_token,
            default_branch=default_branch,
            kova_config_path=kova_config_path,
            active=True,
        )
        self.db.add(integration)
        await self.db.commit()
        await self.db.refresh(integration)
        return integration

    async def get_by_id(self, integration_id: uuid.UUID) -> Integration | None:
        stmt = select(Integration).where(Integration.id == integration_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_provider_and_repo(
        self, provider: str, provider_repo_id: str
    ) -> Integration | None:
        stmt = select(Integration).where(
            Integration.provider == provider,
            Integration.provider_repo_id == provider_repo_id,
            Integration.active.is_(True),
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_project(self, project_id: uuid.UUID) -> list[Integration]:
        stmt = select(Integration).where(
            Integration.project_id == project_id,
            Integration.active.is_(True),
        ).order_by(Integration.created_at.desc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def deactivate(self, integration_id: uuid.UUID) -> bool:
        stmt = (
            update(Integration)
            .where(Integration.id == integration_id)
            .values(active=False)
        )
        res = await self.db.execute(stmt)
        await self.db.commit()
        return res.rowcount > 0

    async def get_decrypted_secrets(self, integration: Integration) -> tuple[str, str | None]:
        try:
            decrypted_secret = decrypt_credential(integration.webhook_secret)
        except Exception:
            decrypted_secret = integration.webhook_secret

        decrypted_token = None
        if integration.access_token:
            try:
                decrypted_token = decrypt_credential(integration.access_token)
            except Exception:
                decrypted_token = integration.access_token
        return decrypted_secret, decrypted_token

    async def create_event(
        self,
        integration_id: uuid.UUID,
        provider_event_id: str,
        event_type: str,
        payload: dict,
    ) -> IntegrationEvent:
        safe_payload = redact_webhook_payload(payload)
        event = IntegrationEvent(
            id=uuid.uuid4(),
            integration_id=integration_id,
            provider_event_id=provider_event_id,
            event_type=event_type,
            payload=safe_payload,
            status="pending",
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def update_event(
        self,
        event_id: uuid.UUID,
        status: str,
        validation_id: uuid.UUID | None = None,
        error: str | None = None,
    ) -> IntegrationEvent | None:
        stmt = select(IntegrationEvent).where(IntegrationEvent.id == event_id)
        res = await self.db.execute(stmt)
        event = res.scalar_one_or_none()
        if not event:
            return None

        event.status = status
        if status in ("completed", "failed"):
            event.processed_at = datetime.now(timezone.utc)
        if validation_id is not None:
            event.validation_id = validation_id
        if error is not None:
            event.error = error

        await self.db.commit()
        await self.db.refresh(event)
        return event
