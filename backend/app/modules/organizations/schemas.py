from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


OrgPlan = Literal["free", "pro", "enterprise"]
OrgRole = Literal["owner", "admin", "member"]
ProjectRole = Literal["viewer", "tester", "admin"]


class OrganizationQuotaBase(BaseModel):
    max_concurrent_executions: int = 2
    max_executions_per_day: int = 50
    max_product_graph_size: int = 100
    max_evidence_storage_mb: int = 100
    allowed_integrations: list[str] = Field(default_factory=lambda: ["github"])


class OrganizationQuotaRead(OrganizationQuotaBase):
    id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationCreate(BaseModel):
    name: str
    slug: Optional[str] = None
    plan: OrgPlan = "free"


class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    plan: Optional[OrgPlan] = None


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    owner_user_id: uuid.UUID
    plan: str
    tier: str
    created_at: datetime
    quota: Optional[OrganizationQuotaRead] = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberRead(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    email: Optional[str] = None
    name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberInvite(BaseModel):
    email: str
    role: OrgRole = "member"


class ProjectMemberRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    email: Optional[str] = None
    name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectMemberAdd(BaseModel):
    user_id: Optional[uuid.UUID] = None
    email: Optional[str] = None
    role: ProjectRole = "viewer"


class AuditEventRead(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    actor_user_id: Optional[uuid.UUID] = None
    project_id: Optional[uuid.UUID] = None
    event_type: str
    action: str
    target: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
