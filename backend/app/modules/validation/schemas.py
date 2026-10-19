from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.validation.models import ValidationMode


class DiscoveredCapability(BaseModel):
    name: str
    description: str | None = None
    routes: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    kind: str = "feature"
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


class FlowRef(BaseModel):
    id: str
    name: str
    reason: str | None = None
    role: str = "target"


class InvariantRef(BaseModel):
    id: str
    name: str
    assertion: str | None = None
    reason: str | None = None


class ImpactReport(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    changed_files: list[str] = Field(default_factory=list)
    affected_capabilities: list[str] = Field(default_factory=list)
    affected_routes: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0
    uncertainty: list[str] = Field(default_factory=list)
    recommended_scope: Literal["targeted", "expanded", "full"] = "targeted"
    downstream_effects: list[str] = Field(default_factory=list)
    product_graph_consulted: bool = False
    unmatched_files: list[str] = Field(default_factory=list)
    affected_flows: list[FlowRef] = Field(default_factory=list)
    affected_invariants: list[InvariantRef] = Field(default_factory=list)
    minimal_execution_plan: Any | None = None
    graph_traversal_log: list[str] = Field(default_factory=list)

    @property
    def uncertainties(self) -> list[str]:
        return self.uncertainty


class ValidationCreate(BaseModel):
    project_id: uuid.UUID
    commit_sha: str | None = None
    branch: str | None = None
    pr_number: int | None = None
    base_url: str | None = None
    scope: Literal["targeted", "expanded", "full"] = "targeted"
    mode: ValidationMode | None = None
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


class ValidationRequest(BaseModel):
    project_id: uuid.UUID
    base_url: str | None = None
    diff_content: str | None = None
    changed_files: list[str] | None = None
    commit_message: str | None = None
    persona: str | None = None
    mode: ValidationMode | None = None
    timeout_seconds: int = 1800


class FlowValidationResult(BaseModel):
    flow_id: uuid.UUID
    flow_name: str
    role: Literal["prerequisite", "target", "teardown"]
    status: Literal["passed", "failed", "unverified", "skipped", "error"]
    duration_ms: int = 0
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    failure_reason: str | None = None
    state_changes: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request: ValidationRequest
    impact_report: ImpactReport
    results: list[FlowValidationResult] = Field(default_factory=list)
    overall_status: Literal["passed", "failed", "unverified", "no_graph", "no_flows"]
    failure_reason: str | None = None
    discoveries: int = 0
    duration_ms: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    signed_url: str | None = None


class FlowResultDiff(BaseModel):
    flow_id: uuid.UUID
    flow_name: str
    status_before: str | None = None       # None if the flow didn't exist in the previous run
    status_after: str | None = None
    status_changed: bool = False
    new_evidence_count: int = 0
    removed_evidence_count: int = 0
    failure_reason_before: str | None = None
    failure_reason_after: str | None = None
    failure_reason_changed: bool = False


class ReportDiff(BaseModel):
    report_before: ValidationReport
    report_after: ValidationReport
    overall_status_changed: bool = False
    flows_added: list[FlowValidationResult] = Field(default_factory=list)      # in after, not in before
    flows_removed: list[FlowValidationResult] = Field(default_factory=list)    # in before, not in after
    flows_changed: list[FlowResultDiff] = Field(default_factory=list)          # in both, with status/evidence changes
    flows_unchanged: list[FlowValidationResult] = Field(default_factory=list)  # in both, no changes
