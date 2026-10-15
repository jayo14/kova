from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.flows.schemas import FlowStateContract, StateAssertion, StateMutation


def _normalize_path(url_pattern: str) -> str:
    cleaned = url_pattern.strip()
    if not cleaned:
        return "/"
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    cleaned = re.sub(r"/+", "/", cleaned)
    if len(cleaned) > 1 and cleaned.endswith("/"):
        cleaned = cleaned[:-1]
    return cleaned


class Goal(BaseModel):
    """What the application is supposed to accomplish."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    persona_id: uuid.UUID | None = None
    success_criteria: list[StateAssertion] = Field(default_factory=list)
    source: Literal["user_provided", "discovered", "inferred", "ai_proposal"] = "discovered"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class Persona(BaseModel):
    """A user role interacting with the application."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    credentials_required: bool = False
    default_capabilities: list[str] = Field(default_factory=list)
    source: str = "discovered"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    """A route in the application."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    url_pattern: str = Field(min_length=1, max_length=1024)
    title: str | None = None
    requires_auth: bool = False
    required_state: list[StateAssertion] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    source: str = "discovered"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)

    @field_validator("url_pattern", mode="before")
    @classmethod
    def validate_url_pattern(cls, v: Any) -> str:
        if not isinstance(v, str):
            v = str(v)
        return _normalize_path(v)


class Action(BaseModel):
    """An interaction on a page."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    page_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    selector: str = Field(min_length=1)
    action_type: Literal["click", "input", "select", "upload", "scroll", "submit"] = "click"
    expected_effect: list[StateAssertion] = Field(default_factory=list)
    mutates: list[str] = Field(default_factory=list)
    source: str = "discovered"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class Capability(BaseModel):
    """A reusable way to establish state in the application."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    requires_capabilities: list[str] = Field(default_factory=list)
    requires_state: list[StateAssertion] = Field(default_factory=list)
    produces_state: list[StateMutation] = Field(default_factory=list)
    kind: Literal["primary", "setup", "shared"] = "primary"
    source_files: list[str] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provider_flow_ids: list[str] = Field(default_factory=list)
    user_edited: bool = False
    source: str = "discovered"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class State(BaseModel):
    """A named condition in the application product model."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    key: str = Field(min_length=1, max_length=128)
    value_type: Literal["bool", "string", "id", "int", "json"] = "bool"
    default_value: Any = None
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class FlowGraphNode(BaseModel):
    """Representation of a flow within the product graph."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    goal_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    page_ids: list[str] = Field(default_factory=list)
    state_contract: FlowStateContract | None = None
    repeatability: str = "repeatable"
    status: str = "active"
    criticality: str = "medium"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class Dependency(BaseModel):
    """An edge between a flow and another flow, capability, or state."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    flow_id: uuid.UUID
    depends_on_kind: Literal["flow", "capability", "state"]
    depends_on_id: str = Field(min_length=1, max_length=255)
    required: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class Invariant(BaseModel):
    """A business rule or assertion that must always remain true."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    assertion: StateAssertion
    checked_by_flow_ids: list[str] = Field(default_factory=list)
    violated_count: int = 0
    source: str = "discovered"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class ProductGraphVersionRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    change_summary: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductGraphExport(BaseModel):
    """Full export representation of a product graph."""
    project_id: uuid.UUID
    version: int = 1
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    goals: list[Goal] = Field(default_factory=list)
    personas: list[Persona] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    states: list[State] = Field(default_factory=list)
    flows: list[FlowGraphNode] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class GraphDiff(BaseModel):
    """Differences between two versions of a product graph."""
    from_version: int
    to_version: int
    added: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    removed: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    changed: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class DiscoveryResult(BaseModel):
    """Discovery output payload to be merged into the Product Graph."""
    goals: list[Goal] = Field(default_factory=list)
    personas: list[Persona] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    states: list[State] = Field(default_factory=list)
    invariants: list[Invariant] = Field(default_factory=list)
    coverage_map: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    ai_proposals: list[AIProposal] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @property
    def review_required(self) -> list[dict[str, Any]]:
        """Return any discovered entities where confidence is below 0.7."""
        items = []
        for p in self.pages:
            if p.confidence < 0.7:
                items.append({"entity_type": "page", "id": str(p.id), "name": p.url_pattern, "confidence": p.confidence, "source": p.source})
        for a in self.actions:
            if a.confidence < 0.7:
                items.append({"entity_type": "action", "id": str(a.id), "name": a.name, "confidence": a.confidence, "source": a.source})
        for c in self.capabilities:
            if c.confidence < 0.7:
                items.append({"entity_type": "capability", "id": str(c.id), "name": c.name, "confidence": c.confidence, "source": c.source})
        for i in self.invariants:
            if i.confidence < 0.7:
                items.append({"entity_type": "invariant", "id": str(i.id), "name": i.name, "confidence": i.confidence, "source": i.source})
        for g in self.goals:
            if g.confidence < 0.7:
                items.append({"entity_type": "goal", "id": str(g.id), "name": g.name, "confidence": g.confidence, "source": g.source})
        return items


class AIProposal(BaseModel):
    stage: str
    input_summary: str
    output_summary: str
    accepted: bool = True
    reasoning: str | None = None
    confidence: float = Field(default=0.8, le=0.9)
