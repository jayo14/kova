"""Pydantic schemas for credential API endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CredentialCreate(BaseModel):
    name: str
    email: str
    password: str

    model_config = ConfigDict(str_min_length=1)


class CredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    email: str
    created_at: datetime
    updated_at: datetime
