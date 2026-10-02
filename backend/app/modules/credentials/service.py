"""Credential service for business logic."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.repository import CredentialRepository
from app.modules.credentials.schemas import CredentialCreate


class CredentialService:
    def __init__(self, db: AsyncSession):
        self.repo = CredentialRepository(db)

    async def create_credential(
        self, project_id: uuid.UUID, data: CredentialCreate
    ):
        return await self.repo.create(
            project_id=project_id,
            name=data.name,
            email=data.email,
            password=data.password,
        )

    async def get_credential(self, credential_id: uuid.UUID):
        return await self.repo.get_by_id(credential_id)

    async def list_credentials(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100):
        return await self.repo.list_by_project(project_id, skip=skip, limit=limit)

    async def delete_credential(self, credential_id: uuid.UUID):
        return await self.repo.delete(credential_id)
