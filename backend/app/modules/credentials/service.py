"""Credential service for business logic."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.repository import CredentialRepository
from app.modules.credentials.schemas import CredentialCreate, CredentialUpdate


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
            persona=data.persona,
            auth_strategy=data.auth_strategy,
        )

    async def update_credential(
        self, credential_id: uuid.UUID, data: "CredentialUpdate"
    ):
        cred = await self.repo.get_by_id(credential_id)
        if cred:
            try:
                from app.modules.flows.auth.session_manager import SessionManager
                await SessionManager().wipe(str(cred.project_id), persona=cred.persona)
            except Exception:
                pass
        return await self.repo.update(
            credential_id=credential_id,
            name=data.name,
            email=data.email,
            password=data.password,
            persona=data.persona,
            auth_strategy=data.auth_strategy,
        )

    async def get_credential(self, credential_id: uuid.UUID):
        return await self.repo.get_by_id(credential_id)

    async def list_credentials(self, project_id: uuid.UUID, skip: int = 0, limit: int = 100):
        return await self.repo.list_by_project(project_id, skip=skip, limit=limit)

    async def delete_credential(self, credential_id: uuid.UUID):
        cred = await self.repo.get_by_id(credential_id)
        if cred:
            try:
                from app.modules.flows.auth.session_manager import SessionManager
                await SessionManager().wipe(str(cred.project_id), persona=cred.persona)
            except Exception:
                pass
        return await self.repo.delete(credential_id)
