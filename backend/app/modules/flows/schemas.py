import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FlowStep(BaseModel):
    action: str
    selector: str | None = None
    value: str | None = None
    credential_id: str | None = None
    description: str | None = None


class FlowCreate(BaseModel):
    project_id: uuid.UUID
    name: str
    description: str | None = None
    persona: dict | None = None
    objective: str | None = None
    steps: list[FlowStep] = []
    success_condition: dict | None = None

    model_config = ConfigDict(str_min_length=1)


class FlowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    persona: dict | None = None
    objective: str | None = None
    steps: list[FlowStep] | None = None
    success_condition: dict | None = None


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
    created_at: datetime
    updated_at: datetime
