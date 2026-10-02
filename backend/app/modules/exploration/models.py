import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class ExplorationStatus(str, enum.Enum):
    CREATED = "CREATED"
    CONNECTING = "CONNECTING"
    LOADING = "LOADING"
    VALIDATING_PAGE = "VALIDATING_PAGE"
    EXPLORING = "EXPLORING"
    UNDERSTANDING = "UNDERSTANDING"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTHENTICATING = "AUTHENTICATING"
    ASKING = "ASKING"
    DISCOVERING = "DISCOVERING"
    PLANNING = "PLANNING"
    READY = "READY"
    MISSION_CREATED = "MISSION_CREATED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


VALID_EXPLORATION_TRANSITIONS: dict[str, set[str]] = {
    ExplorationStatus.CREATED.value: {
        ExplorationStatus.CONNECTING.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.CONNECTING.value: {
        ExplorationStatus.LOADING.value,
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.LOADING.value: {
        ExplorationStatus.VALIDATING_PAGE.value,
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.VALIDATING_PAGE.value: {
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.UNDERSTANDING.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.EXPLORING.value: {
        ExplorationStatus.UNDERSTANDING.value,
        ExplorationStatus.AUTH_REQUIRED.value,
        ExplorationStatus.ASKING.value,
        ExplorationStatus.DISCOVERING.value,
        ExplorationStatus.READY.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.UNDERSTANDING.value: {
        ExplorationStatus.AUTH_REQUIRED.value,
        ExplorationStatus.ASKING.value,
        ExplorationStatus.DISCOVERING.value,
        ExplorationStatus.READY.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.AUTH_REQUIRED.value: {
        ExplorationStatus.AUTHENTICATING.value,
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.AUTHENTICATING.value: {
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.UNDERSTANDING.value,
        ExplorationStatus.AUTH_REQUIRED.value,
        ExplorationStatus.DISCOVERING.value,
        ExplorationStatus.READY.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.ASKING.value: {
        ExplorationStatus.DISCOVERING.value,
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.DISCOVERING.value: {
        ExplorationStatus.PLANNING.value,
        ExplorationStatus.READY.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.PLANNING.value: {
        ExplorationStatus.READY.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.READY.value: {
        ExplorationStatus.MISSION_CREATED.value,
        ExplorationStatus.EXECUTING.value,
        ExplorationStatus.COMPLETED.value,
        ExplorationStatus.EXPLORING.value,
        ExplorationStatus.CANCELLED.value,
        ExplorationStatus.FAILED.value,
    },
    ExplorationStatus.MISSION_CREATED.value: {
        ExplorationStatus.EXECUTING.value,
        ExplorationStatus.CANCELLED.value,
        ExplorationStatus.FAILED.value,
    },
    ExplorationStatus.EXECUTING.value: {
        ExplorationStatus.COMPLETED.value,
        ExplorationStatus.FAILED.value,
        ExplorationStatus.CANCELLED.value,
    },
    ExplorationStatus.COMPLETED.value: set(),
    ExplorationStatus.FAILED.value: {
        ExplorationStatus.CONNECTING.value,
    },
    ExplorationStatus.CANCELLED.value: set(),
}


def validate_exploration_transition(from_status: str, to_status: str) -> bool:
    """Validate if an exploration status transition is valid."""
    if from_status == to_status:
        return True
    allowed = VALID_EXPLORATION_TRANSITIONS.get(from_status, set())
    return to_status in allowed


class ExplorationSession(Base):
    __tablename__ = "exploration_sessions"
    __table_args__ = (
        Index("ix_exploration_sessions_user_id", "user_id"),
        Index("ix_exploration_sessions_status", "status"),
        Index("ix_exploration_sessions_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ExplorationStatus.CREATED.value
    )
    selected_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    discoveries: Mapped[list[dict]] = mapped_column(JSONCompat, nullable=False, default=list)
    candidate_missions: Mapped[list[dict]] = mapped_column(JSONCompat, nullable=False, default=list)
    question: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True)
    credential_request: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User")
    project = relationship("Project")


class ExplorationEvent(Base):
    __tablename__ = "exploration_events"
    __table_args__ = (
        Index("ix_exploration_events_exploration_id", "exploration_id"),
        Index("ix_exploration_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exploration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exploration_sessions.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session = relationship("ExplorationSession", backref="events")
