"""Add continuous validation, regression runs, and persistent product knowledge.

Revision ID: 012
Revises: 011
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "012"
down_revision: Union[str, Sequence[str], None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend flows with capability, routes, status, and criticality
    op.add_column("flows", sa.Column("status", sa.String(length=32), server_default="active", nullable=False))
    op.add_column("flows", sa.Column("capability", sa.String(length=128), nullable=True))
    op.add_column("flows", sa.Column("routes", postgresql.JSONB(), server_default="[]", nullable=False))
    op.add_column("flows", sa.Column("criticality", sa.String(length=32), server_default="medium", nullable=False))

    # 2. Create product_models table
    op.create_table(
        "product_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("name", sa.String(length=255), server_default="Default Product Model", nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("routes", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("roles", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("entities", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_models_project_id", "product_models", ["project_id"])

    # 3. Create validation_runs table
    op.create_table(
        "validation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("scope", sa.String(length=32), server_default="targeted", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="RUNNING", nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("selected_flow_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("execution_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("impact_report", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("baseline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("validation_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("baseline_diff", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("summary", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_validation_runs_project_id", "validation_runs", ["project_id"])
    op.create_index("ix_validation_runs_status", "validation_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_validation_runs_status", table_name="validation_runs")
    op.drop_index("ix_validation_runs_project_id", table_name="validation_runs")
    op.drop_table("validation_runs")

    op.drop_index("ix_product_models_project_id", table_name="product_models")
    op.drop_table("product_models")

    op.drop_column("flows", "criticality")
    op.drop_column("flows", "routes")
    op.drop_column("flows", "capability")
    op.drop_column("flows", "status")
