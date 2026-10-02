"""Credential repository for DB access."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.models import Credential


class CredentialRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        project_id: uuid.UUID,
        name: str,
        email: str,
        password: str,
    ) -> Credential:
        credential = Credential(
            project_id=project_id,
            name=name,
            email=email,
            password=password,
        )
        self.db.add(credential)
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
