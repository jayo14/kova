import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from app.infrastructure.database.base import Base, JSONCompat


class IntegrationProvider(str, enum.Enum):
    GITHUB = "github"
    GITLAB = "gitlab"


class IntegrationEventStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Integration(Base):
    __tablename__ = "integrations"
    __table_args__ = (
        Index("ix_integrations_project_id", "project_id"),
        Index("ix_integrations_provider_repo_id", "provider_repo_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # github | gitlab
    provider_repo_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_installation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_secret: Mapped[str] = mapped_column(Text, nullable=False)  # encrypted with Fernet
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted with Fernet
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    kova_config_path: Mapped[str] = mapped_column(String(255), nullable=False, default=".kova.yml")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", backref=backref("integrations", passive_deletes=True))


class IntegrationEvent(Base):
    __tablename__ = "integration_events"
    __table_args__ = (
        Index("ix_integration_events_integration_id", "integration_id"),
        Index("ix_integration_events_status", "status"),
        Index("ix_integration_events_provider_event_id", "provider_event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("validation_reports.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    integration = relationship("Integration", backref=backref("events", passive_deletes=True))
    validation_report = relationship("ValidationReportModel")
