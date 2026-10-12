from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoveredCapability(BaseModel):
    name: str
    description: str | None = None
    routes: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    is_inferred: bool = False
    confidence: float = 1.0
    provenance: str = "observed"


class ProductModelCreate(BaseModel):
    project_id: uuid.UUID
    name: str = "Default Product Model"
    purpose: str | None = None
    capabilities: list[dict] = Field(default_factory=list)
    routes: list[dict] = Field(default_factory=list)
    roles: list[dict] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ProductModelUpdate(BaseModel):
    name: str | None = None
    purpose: str | None = None
    capabilities: list[dict] | None = None
    routes: list[dict] | None = None
    roles: list[dict] | None = None
    entities: list[dict] | None = None
    metadata: dict | None = None


class ProductModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    name: str
    purpose: str | None
    capabilities: list[dict]
    routes: list[dict]
    roles: list[dict]
    entities: list[dict]
    metadata: dict = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ImpactReport(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    affected_capabilities: list[str] = Field(default_factory=list)
    affected_routes: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0
    uncertainty: list[str] = Field(default_factory=list)
    recommended_scope: Literal["targeted", "expanded", "full"] = "targeted"
    downstream_effects: list[str] = Field(default_factory=list)


class ValidationCreate(BaseModel):
    project_id: uuid.UUID
    commit_sha: str | None = None
    branch: str | None = None
    pr_number: int | None = None
    base_url: str | None = None
    scope: Literal["targeted", "expanded", "full"] = "targeted"
    changed_files: list[str] | None = None
    diff_content: str | None = None
    commit_message: str | None = None
    fail_on_healed: bool = False


class BaselineDiff(BaseModel):
    baseline_run_id: uuid.UUID | None = None
    newly_failing: list[str] = Field(default_factory=list)
    recovered: list[str] = Field(default_factory=list)
    unchanged_passing: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)
    status_changed: list[dict] = Field(default_factory=list)


class ValidationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    commit_sha: str | None
    branch: str | None
    pr_number: int | None
    base_url: str | None
    scope: str
    status: str
    exit_code: int | None
    selected_flow_ids: list[str]
    execution_ids: list[str]
    impact_report: dict
    baseline_run_id: uuid.UUID | None
    baseline_diff: dict
    summary: dict
    created_at: datetime
    completed_at: datetime | None
