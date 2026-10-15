import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class EvidenceType(str, enum.Enum):
    SCREENSHOT = "SCREENSHOT"
    VERIFICATION = "VERIFICATION"
    ARTIFACT = "ARTIFACT"


class EvidenceStatus(str, enum.Enum):
    CAPTURED = "CAPTURED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_execution_id", "execution_id"),
        Index("ix_evidence_type", "type"),
        Index("ix_evidence_purpose", "purpose"),
        Index("ix_evidence_step_id", "step_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(50), nullable=False, default="legacy", server_default="legacy"
    )
    step_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=EvidenceStatus.CAPTURED.value
    )
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dom_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    a11y_tree: Mapped[str | None] = mapped_column(Text, nullable=True)
    network_log: Mapped[list | dict | None] = mapped_column(JSONCompat, nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    trace_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    element_locator: Mapped[str | None] = mapped_column(String(500), nullable=True)
    timestamp_range: Mapped[list | None] = mapped_column(JSONCompat, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict] = mapped_column("metadata", JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    execution = relationship("Execution", backref="evidence_items")
