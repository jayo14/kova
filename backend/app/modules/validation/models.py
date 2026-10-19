import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from app.infrastructure.database.base import Base, JSONCompat

class ValidationMode(str, enum.Enum):
    """The 5 validation modes defined in brief §9."""
    FUNCTIONAL = "functional"        # Does a feature perform its intended operation?
    WORKFLOW = "workflow"             # Can a user complete an end-to-end journey?
    REGRESSION = "regression"         # Does previously verified behavior still work?
    EXPLORATORY = "exploratory"       # Can Kova discover unexpected behaviors?
    VISUAL = "visual"                 # Does the rendered interface match expectations?


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
    """DEPRECATED: Use the relational ProductGraph in `app.modules.product_graph` instead.

    This flat JSON-based model is maintained for backward compatibility.
    Use `convert_legacy_product_model_to_graph` to convert instances to structured entities.
    """
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

    project = relationship("Project", backref=backref("product_models", passive_deletes=True))


def convert_legacy_product_model_to_graph(model: ProductModel) -> dict[str, Any]:
    """Helper to convert a legacy flat ProductModel to structured ProductGraph entities."""
    pages = [
        {"url_pattern": r if isinstance(r, str) else r.get("path", "/"), "provenance": "observed"}
        for r in (model.routes or [])
    ]
    capabilities = [
        {"name": c if isinstance(c, str) else c.get("name", "unknown"), "provenance": "observed"}
        for c in (model.capabilities or [])
    ]
    personas = [
        {"name": p if isinstance(p, str) else p.get("name", "user"), "provenance": "observed"}
        for p in (model.roles or [])
    ]
    states = [
        {"key": e if isinstance(e, str) else e.get("key", "state"), "provenance": "observed"}
        for e in (model.entities or [])
    ]
    return {
        "project_id": str(model.project_id),
        "pages": pages,
        "capabilities": capabilities,
        "personas": personas,
        "states": states,
    }


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

    project = relationship("Project", backref=backref("validation_runs", passive_deletes=True))
    baseline_run = relationship("ValidationRun", remote_side=[id])


class ValidationReportModel(Base):
    __tablename__ = "validation_reports"
    __table_args__ = (
        Index("ix_validation_reports_project_id", "project_id"),
        Index("ix_validation_reports_overall_status", "overall_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    impact_report: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    results: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    evidence_summary: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    signed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project = relationship("Project", backref=backref("validation_reports", passive_deletes=True))


class SignedUrlModel(Base):
    __tablename__ = "signed_urls"
    __table_args__ = (
        Index("ix_signed_urls_validation_id", "validation_id"),
        Index("ix_signed_urls_execution_id", "execution_id"),
        Index("ix_signed_urls_url", "url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    validation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("validation_reports.id", ondelete="CASCADE"), nullable=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), nullable=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    validation_report = relationship("ValidationReportModel", backref=backref("signed_urls", passive_deletes=True))
    execution = relationship("Execution", backref=backref("signed_urls", passive_deletes=True))


class VisualReferenceModel(Base):
    __tablename__ = "visual_references"
    __table_args__ = (
        Index("ix_visual_references_flow_id", "flow_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    flow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flows.id", ondelete="CASCADE"), nullable=False
    )
    screenshot_url: Mapped[str] = mapped_column(Text, nullable=False)
    a11y_tree: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    viewport: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="Baseline")
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    flow = relationship("Flow", backref=backref("visual_references", passive_deletes=True))

