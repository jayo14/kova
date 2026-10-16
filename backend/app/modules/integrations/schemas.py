from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IntegrationCreate(BaseModel):
    project_id: uuid.UUID
    provider: Literal["github", "gitlab"]
    provider_repo_id: str
    webhook_secret: str
    access_token: str | None = None
    provider_installation_id: str | None = None
    default_branch: str = "main"
    kova_config_path: str = ".kova.yml"


class IntegrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    provider_repo_id: str
    provider_installation_id: str | None = None
    default_branch: str
    kova_config_path: str
    active: bool
    created_at: datetime
    updated_at: datetime


class IntegrationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    integration_id: uuid.UUID
    provider_event_id: str
    event_type: str
    payload: dict = Field(default_factory=dict)
    received_at: datetime
    processed_at: datetime | None = None
    validation_id: uuid.UUID | None = None
    status: str
    error: str | None = None


class KovaConfig(BaseModel):
    base_url: str | None = None
    persona: str | None = None
    skip_flows: list[str] = Field(default_factory=list)
    only_flows: list[str] = Field(default_factory=list)
    rediscover_on_config_change: bool = True
    fail_on_unverified: bool = True
    timeout_seconds: int = 1800
