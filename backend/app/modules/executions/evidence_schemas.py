import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    type: str
    title: str
    description: str | None
    status: str
    mime_type: str | None
    metadata: dict
    created_at: datetime


class EvidenceDetailRead(EvidenceRead):
    """Evidence with a short-lived signed URL for artifact access."""
    url: str | None = None
