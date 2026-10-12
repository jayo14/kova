from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class FlowCreate(BaseModel):
    project_id: uuid.UUID
    name: str
    description: str | None = None
    persona: dict | None = None
    objective: str | None = None
    steps: list[FlowStep] = Field(default_factory=list)
    success_condition: dict | None = None
    preconditions: dict | None = None

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
    created_at: datetime
    updated_at: datetime
