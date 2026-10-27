"""Add versioned test suites and repeatable suite runs.

Revision ID: 032
Revises: 031
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "032"
down_revision: Union[str, Sequence[str], None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    if "test_suites" not in tables:
        op.create_table(
            "test_suites",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("project_id", "name", name="uq_test_suites_project_id_name"),
        )
        op.create_index("ix_test_suites_project_id", "test_suites", ["project_id"])

    if "test_suite_versions" not in tables:
        op.create_table(
            "test_suite_versions",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("suite_id", sa.Uuid(), sa.ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("flow_snapshot", json_type, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("checksum", sa.String(length=64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("suite_id", "version", name="uq_test_suite_versions_suite_id_version"),
        )
        op.create_index("ix_test_suite_versions_suite_id", "test_suite_versions", ["suite_id"])

    if "suite_runs" not in tables:
        op.create_table(
            "suite_runs",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("suite_id", sa.Uuid(), sa.ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("suite_version", sa.Integer(), nullable=False),
            sa.Column("suite_snapshot", json_type, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="full"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
            sa.Column("baseline_run_id", sa.Uuid(), sa.ForeignKey("suite_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("baseline_reason", sa.Text(), nullable=True),
            sa.Column("comparison", json_type, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("changed_files", json_type, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("commit_sha", sa.String(length=128), nullable=True),
            sa.Column("branch", sa.String(length=255), nullable=True),
            sa.Column("summary", json_type, nullable=False, server_default=sa.text("'{}'")),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_suite_runs_suite_id", "suite_runs", ["suite_id"])
        op.create_index("ix_suite_runs_project_id", "suite_runs", ["project_id"])
        op.create_index("ix_suite_runs_status", "suite_runs", ["status"])

    if "suite_run_items" not in tables:
        op.create_table(
            "suite_run_items",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("suite_run_id", sa.Uuid(), sa.ForeignKey("suite_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("flow_id", sa.Uuid(), sa.ForeignKey("flows.id", ondelete="SET NULL"), nullable=True),
            sa.Column("flow_name", sa.String(length=255), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("executions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("assertions", json_type, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("failure_signature", sa.String(length=255), nullable=True),
            sa.Column("classification", sa.String(length=64), nullable=True),
            sa.Column("unstable", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_suite_run_items_run_id", "suite_run_items", ["suite_run_id"])
        op.create_index("ix_suite_run_items_flow_id", "suite_run_items", ["flow_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "suite_run_items" in tables:
        op.drop_index("ix_suite_run_items_flow_id", table_name="suite_run_items")
        op.drop_index("ix_suite_run_items_run_id", table_name="suite_run_items")
        op.drop_table("suite_run_items")
    if "suite_runs" in tables:
        op.drop_index("ix_suite_runs_status", table_name="suite_runs")
        op.drop_index("ix_suite_runs_project_id", table_name="suite_runs")
        op.drop_index("ix_suite_runs_suite_id", table_name="suite_runs")
        op.drop_table("suite_runs")
    if "test_suite_versions" in tables:
        op.drop_index("ix_test_suite_versions_suite_id", table_name="test_suite_versions")
        op.drop_table("test_suite_versions")
    if "test_suites" in tables:
        op.drop_index("ix_test_suites_project_id", table_name="test_suites")
        op.drop_table("test_suites")
