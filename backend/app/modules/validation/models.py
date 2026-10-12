import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class ValidationScope(str, enum.Enum):
    TARGETED = "targeted"
    EXPANDED = "expanded"
    FULL = "full"


class ValidationStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"
    ERROR = "ERROR"


class ProductModel(Base):
    __tablename__ = "product_models"
    __table_args__ = (
        Index("ix_product_models_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default Product Model")
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    routes: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    roles: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    entities: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", backref="product_models")


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    __table_args__ = (
        Index("ix_validation_runs_project_id", "project_id"),
        Index("ix_validation_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ValidationScope.TARGETED.value, server_default="targeted"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ValidationStatus.RUNNING.value, server_default="RUNNING"
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_flow_ids: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    execution_ids: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    impact_report: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("validation_runs.id", ondelete="SET NULL"), nullable=True
    )
    baseline_diff: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project = relationship("Project", backref="validation_runs")
    baseline_run = relationship("ValidationRun", remote_side=[id])
