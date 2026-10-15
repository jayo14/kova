"""Credential repository for DB access."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.models import Credential
from app.modules.credentials.crypto import encrypt_credential


class CredentialRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        project_id: uuid.UUID,
        name: str,
        email: str,
        password: str,
        persona: str | None = None,
        auth_strategy: str | None = "password_form",
    ) -> Credential:
        encrypted_password = encrypt_credential(password)
        credential = Credential(
            project_id=project_id,
            name=name,
            email=email,
            password=encrypted_password,
            persona=persona,
            auth_strategy=auth_strategy or "password_form",
        )
        self.db.add(credential)
        await self.db.flush()
        await self.db.refresh(credential)
        return credential

    async def update(
        self,
        credential_id: uuid.UUID,
        name: str | None = None,
        email: str | None = None,
        password: str | None = None,
        persona: str | None = None,
        auth_strategy: str | None = None,
    ) -> Credential | None:
        credential = await self.get_by_id(credential_id)
        if credential is None:
            return None
        if name is not None:
            credential.name = name
        if email is not None:
            credential.email = email
        if password is not None:
            credential.password = encrypt_credential(password)
        if persona is not None:
            credential.persona = persona
        if auth_strategy is not None:
            credential.auth_strategy = auth_strategy
        await self.db.flush()
        await self.db.refresh(credential)
        return credential

    async def get_by_id(self, credential_id: uuid.UUID) -> Credential | None:
        result = await self.db.execute(
            select(Credential).where(Credential.id == credential_id)
        )
        return result.scalar_one_or_none()

    async def get_by_project_and_name(
        self, project_id: uuid.UUID, name: str
    ) -> Credential | None:
        result = await self.db.execute(
            select(Credential).where(
                Credential.project_id == project_id,
                Credential.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> list[Credential]:
        result = await self.db.execute(
            select(Credential)
            .where(Credential.project_id == project_id)
            .order_by(Credential.created_at.desc(), Credential.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, credential_id: uuid.UUID) -> bool:
        credential = await self.get_by_id(credential_id)
        if credential is None:
            return False
        await self.db.delete(credential)
        await self.db.flush()
        return True
