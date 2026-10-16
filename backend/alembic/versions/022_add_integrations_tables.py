"""Add integrations and integration_events tables for GitHub and GitLab PR automations.

Revision ID: 022
Revises: 021
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "022"
down_revision: Union[str, Sequence[str], None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_repo_id", sa.String(length=255), nullable=False),
        sa.Column("provider_installation_id", sa.String(length=255), nullable=True),
        sa.Column("webhook_secret", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.String(length=255), server_default="main", nullable=False),
        sa.Column("kova_config_path", sa.String(length=255), server_default=".kova.yml", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integrations_project_id", "integrations", ["project_id"], unique=False)
    op.create_index("ix_integrations_provider_repo_id", "integrations", ["provider_repo_id"], unique=False)

    op.create_table(
        "integration_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("integration_id", sa.UUID(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["validation_id"], ["validation_reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_events_integration_id", "integration_events", ["integration_id"], unique=False)
    op.create_index("ix_integration_events_status", "integration_events", ["status"], unique=False)
    op.create_index("ix_integration_events_provider_event_id", "integration_events", ["provider_event_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_integration_events_provider_event_id", table_name="integration_events")
    op.drop_index("ix_integration_events_status", table_name="integration_events")
    op.drop_index("ix_integration_events_integration_id", table_name="integration_events")
    op.drop_table("integration_events")

    op.drop_index("ix_integrations_provider_repo_id", table_name="integrations")
    op.drop_index("ix_integrations_project_id", table_name="integrations")
    op.drop_table("integrations")
