import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.executions.models import ExecutionStatus


class ExecutionCreate(BaseModel):
    flow_id: uuid.UUID


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flow_id: uuid.UUID
    status: ExecutionStatus
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ExecutionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    event_type: str
    payload: dict
    created_at: datetime
