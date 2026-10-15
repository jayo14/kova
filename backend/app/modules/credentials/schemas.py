"""Pydantic schemas for credential API endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class CredentialCreate(BaseModel):
    name: str
    email: str
    password: str
    persona: str | None = None
    auth_strategy: Literal["password_form", "magic_link", "oauth", "otp"] | None = "password_form"

    model_config = ConfigDict(str_min_length=1)


class CredentialUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    password: str | None = None
    persona: str | None = None
    auth_strategy: Literal["password_form", "magic_link", "oauth", "otp"] | None = None


class CredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    email: str
    persona: str | None = None
    auth_strategy: str | None = "password_form"
    created_at: datetime
    updated_at: datetime

