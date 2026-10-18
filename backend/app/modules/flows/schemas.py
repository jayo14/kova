from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_unique_step_ids(steps: list[FlowStep] | None) -> None:
    if steps is None:
        return
    ids = [step.step_id for step in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("step_id values must be unique within a flow")


class FlowStep(BaseModel):
    step_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=40)
    selector: str | None = None
    value: str | None = None
    credential_id: str | None = None
    description: str | None = None
    postcondition: dict | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def require_action_target(self):
        if self.action.lower() in {"click", "type", "fill", "select", "check", "uncheck", "upload"} and not any(
            (self.selector, getattr(self, "target", None), getattr(self, "label", None), getattr(self, "role", None), getattr(self, "test_id", None))
        ):
            raise ValueError(f"{self.action} step requires an element target")
        if self.action.lower() == "navigate" and not (self.value or getattr(self, "url", None)):
            raise ValueError("navigate step requires a URL")
        return self


ResetStrategy = Literal["none", "re_establish", "create_new", "skip_if_exists"]


class StateAssertion(BaseModel):
    """A condition the application must satisfy."""
    key: str
    value: Any = True
    predicate: Literal["eq", "ne", "in", "contains", "exists"] = "eq"

    def is_satisfied_by_state(self, current_state: dict[str, Any]) -> bool:
        if self.predicate == "exists":
            return self.key in current_state and current_state[self.key] is not None
        if self.key not in current_state:
            return False
        val = current_state[self.key]
        if self.predicate == "eq":
            return val == self.value
        elif self.predicate == "ne":
            return val != self.value
        elif self.predicate == "in":
            try:
                return val in self.value
            except TypeError:
                return False
        elif self.predicate == "contains":
            try:
                return self.value in val
            except TypeError:
                return False
        return False

    def is_satisfied_by_assertion(self, produced: StateAssertion) -> bool:
        if self.key != produced.key:
            return False
        if self.predicate == "exists":
            return produced.value is not None
        if self.predicate == "eq":
            if produced.predicate == "eq":
                return self.value == produced.value
            return produced.value == self.value
        elif self.predicate == "ne":
            return produced.value != self.value
        elif self.predicate == "in":
            try:
                return produced.value in self.value
            except TypeError:
                return False
        elif self.predicate == "contains":
            try:
                return self.value in produced.value
            except TypeError:
                return False
        return False


class State(BaseModel):
    """Representation of an observed or tracked application state."""
    key: str
    value: Any = None


class StateMutation(BaseModel):
    """A declared mutation to application state."""
    key: str
    action: Literal["set", "delete", "mutate"] = "mutate"
    value: Any = None


class Prerequisite(BaseModel):
    """A prerequisite requirement for a flow."""
    assertion: StateAssertion
    reason: str | None = None


class Capability(BaseModel):
    """A reusable way to establish a state."""
    name: str
    produces: list[StateAssertion]
    cost: int = 1
    persona: str | None = None
    requires_credential: bool = False
    reset_strategy: ResetStrategy = "none"


class FlowStateContract(BaseModel):
    """Contract declaring state prerequisites, productions, mutations, and resets."""
    requires: list[StateAssertion] = Field(default_factory=list)
    produces: list[StateAssertion] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    mutates: list[str] = Field(default_factory=list)
    reset_strategy: ResetStrategy = "none"
    cost: int = 1
    persona: str | None = None
    requires_credential: bool = False


class FlowDependency(BaseModel):
    kind: Literal["flow", "capability"]
    value: str = Field(min_length=1, max_length=200)


class FlowCreate(BaseModel):
    """Schema for creating a flow.

    Agent-executable flow contract:
    When objective is set and steps is empty ([]), the flow is dispatched
    to the autonomous agent loop when settings.AGENT_EXECUTION_ENABLED is true.
    """
    project_id: uuid.UUID
    name: str
    description: str | None = None
    persona: dict | None = None
    objective: str | None = None
    steps: list[FlowStep] = Field(default_factory=list)
    success_condition: dict | None = None
    preconditions: dict | None = None
    dependencies: list[FlowDependency] = Field(default_factory=list)
    provides_capabilities: list[str] = Field(default_factory=list)
    repeatability: Literal["repeatable", "non_repeatable"] = "repeatable"
    reset_strategy: str | None = None
    status: Literal["active", "stale", "disabled", "requires_review"] = "active"
    capability: str | None = None
    routes: list[str] = Field(default_factory=list)
    criticality: Literal["critical", "high", "medium", "low"] = "medium"
    state_contract: FlowStateContract | None = None
    goal_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    page_ids: list[str] = Field(default_factory=list)
    source: Literal["legacy", "deterministic", "ai_proposal", "user_provided"] = "deterministic"
    confidence: float = 1.0
    active: bool = False
    json_repr: dict | None = None
    gherkin_repr: str | None = None

    @model_validator(mode="after")
    def unique_step_ids(self):
        _validate_unique_step_ids(self.steps)
        return self

    model_config = ConfigDict(str_min_length=1)


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    persona: dict | None = None
    objective: str | None = None
    steps: list[FlowStep] | None = None
    success_condition: dict | None = None
    preconditions: dict | None = None
    dependencies: list[FlowDependency] | None = None
    provides_capabilities: list[str] | None = None
    repeatability: Literal["repeatable", "non_repeatable"] | None = None
    reset_strategy: str | None = None
    status: Literal["active", "stale", "disabled", "requires_review"] | None = None
    capability: str | None = None
    routes: list[str] | None = None
    criticality: Literal["critical", "high", "medium", "low"] | None = None
    state_contract: FlowStateContract | None = None
    goal_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    page_ids: list[str] | None = None
    source: Literal["legacy", "deterministic", "ai_proposal", "user_provided"] | None = None
    confidence: float | None = None
    active: bool | None = None
    json_repr: dict | None = None
    gherkin_repr: str | None = None

    @model_validator(mode="after")
    def unique_step_ids(self):
        _validate_unique_step_ids(self.steps)
        return self


class FlowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    persona: dict | None
    objective: str | None
    steps: list[dict]
    success_condition: dict | None
    preconditions: dict | None
    version: int
    dependencies: list[dict]
    provides_capabilities: list[str]
    repeatability: str
    reset_strategy: str | None
    status: str = "active"
    capability: str | None = None
    routes: list[str] = Field(default_factory=list)
    criticality: str = "medium"
    state_contract: FlowStateContract | None = None
    goal_id: uuid.UUID | None = None
    persona_id: uuid.UUID | None = None
    page_ids: list[str] = Field(default_factory=list)
    source: str = "legacy"
    confidence: float = 1.0
    active: bool = True
    json_repr: dict | None = None
    gherkin_repr: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("state_contract", mode="before")
    @classmethod
    def validate_state_contract(cls, v: Any) -> Any:
        if v == {} or v is None:
            return None
        return v

    @property
    def requires_state(self) -> list[StateAssertion]:
        return self.state_contract.requires if self.state_contract else []

    @property
    def produces_state(self) -> list[StateAssertion]:
        return self.state_contract.produces if self.state_contract else []

    @property
    def mutates_state(self) -> list[str]:
        return self.state_contract.mutates if self.state_contract else []

    @property
    def cost(self) -> int:
        return self.state_contract.cost if self.state_contract else 1


FlowSchema = FlowRead
