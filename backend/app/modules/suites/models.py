"""Persistent, versioned regression suites."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, JSONCompat


class TestSuite(Base):
    __tablename__ = "test_suites"
    __table_args__ = (
        Index("ix_test_suites_project_id", "project_id"),
        UniqueConstraint("project_id", "name", name="uq_test_suites_project_id_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    current_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TestSuiteVersion(Base):
    __tablename__ = "test_suite_versions"
    __table_args__ = (
        UniqueConstraint(
            "suite_id", "version", name="uq_test_suite_versions_suite_id_version"
        ),
        Index("ix_test_suite_versions_suite_id", "suite_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    flow_snapshot: Mapped[list] = mapped_column(
        JSONCompat, nullable=False, default=list
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SuiteRun(Base):
    __tablename__ = "suite_runs"
    __table_args__ = (
        Index("ix_suite_runs_suite_id", "suite_id"),
        Index("ix_suite_runs_project_id", "project_id"),
        Index("ix_suite_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    suite_version: Mapped[int] = mapped_column(Integer, nullable=False)
    suite_snapshot: Mapped[list] = mapped_column(
        JSONCompat, nullable=False, default=list
    )
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="full")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    baseline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suite_runs.id", ondelete="SET NULL"), nullable=True
    )
    baseline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    comparison: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    changed_files: Mapped[list] = mapped_column(
        JSONCompat, nullable=False, default=list
    )
    commit_sha: Mapped[str | None] = mapped_column(String(128), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SuiteRunItem(Base):
    __tablename__ = "suite_run_items"
    __table_args__ = (
        Index("ix_suite_run_items_run_id", "suite_run_id"),
        Index("ix_suite_run_items_flow_id", "flow_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suite_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suite_runs.id", ondelete="CASCADE"), nullable=False
    )
    flow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("flows.id", ondelete="SET NULL"), nullable=True
    )
    flow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("executions.id", ondelete="SET NULL"), nullable=True
    )
    assertions: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    failure_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unstable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
