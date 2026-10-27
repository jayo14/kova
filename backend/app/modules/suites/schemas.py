from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SuiteMode = Literal["full", "targeted", "prioritized"]


class SuiteCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    flow_ids: list[uuid.UUID] = Field(default_factory=list)


class SuiteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    active: bool | None = None
    flow_ids: list[uuid.UUID] | None = None
    notes: str | None = None


class SuiteVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    version: int
    flow_snapshot: list[dict]
    checksum: str
    notes: str | None = None
    created_at: datetime


class SuiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None = None
    active: bool
    current_version: int
    created_at: datetime
    updated_at: datetime


class SuiteDetail(SuiteRead):
    version: SuiteVersionRead
    last_run: "SuiteRunRead | None" = None


class SuiteRunRequest(BaseModel):
    mode: SuiteMode = "full"
    baseline_run_id: uuid.UUID | None = None
    changed_files: list[str] = Field(default_factory=list)
    commit_sha: str | None = None
    branch: str | None = None


class SuiteRunItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flow_id: uuid.UUID | None
    flow_name: str
    position: int
    status: str
    duration_ms: int
    execution_id: uuid.UUID | None = None
    assertions: list[dict]
    failure_signature: str | None = None
    classification: str | None = None
    unstable: bool
    rationale: str | None = None


class SuiteRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    project_id: uuid.UUID
    suite_version: int
    mode: str
    status: str
    baseline_run_id: uuid.UUID | None = None
    baseline_reason: str | None = None
    comparison: dict
    changed_files: list[str]
    commit_sha: str | None = None
    branch: str | None = None
    summary: dict
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class SuiteRunDetail(SuiteRunRead):
    items: list[SuiteRunItemRead] = Field(default_factory=list)


class FlakyFlowRead(BaseModel):
    flow_id: uuid.UUID
    flow_name: str
    transitions: int
    runs_considered: int
    statuses: list[str]
    flaky: bool


class FlakinessRead(BaseModel):
    suite_id: uuid.UUID
    flows: list[FlakyFlowRead]
