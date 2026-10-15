import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    type: str
    title: str
    purpose: str = "legacy"
    step_id: str | None = None
    description: str | None
    status: str
    mime_type: str | None
    dom_snapshot: str | None = None
    a11y_tree: str | None = None
    network_log: list | dict | None = None
    video_url: str | None = None
    trace_url: str | None = None
    element_locator: str | None = None
    timestamp_range: list[float] | None = None
    note: str | None = None
    metadata: dict
    created_at: datetime


class EvidenceDetailRead(EvidenceRead):
    """Evidence with a short-lived signed URL for artifact access."""
    url: str | None = None
