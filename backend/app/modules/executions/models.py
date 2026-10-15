import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class ExecutionStatus(str, enum.Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    INITIALIZING = "INITIALIZING"
    BROWSER_READY = "BROWSER_READY"
    PLANNING = "PLANNING"
    RESOLVING_PREREQUISITES = "RESOLVING_PREREQUISITES"
    PREREQUISITE_FAILED = "PREREQUISITE_FAILED"
    CONTAMINATION_DETECTED = "CONTAMINATION_DETECTED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    HUMAN_CONTROLLED = "HUMAN_CONTROLLED"
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    NEEDS_INPUT = "NEEDS_INPUT"
    UNVERIFIED = "UNVERIFIED"


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_flow_id", "flow_id"),
        Index("ix_executions_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flows.id", ondelete="CASCADE"), nullable=False
    )
    flow_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    flow_snapshot: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ExecutionStatus.CREATED.value
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    flow = relationship("Flow", backref="executions")
