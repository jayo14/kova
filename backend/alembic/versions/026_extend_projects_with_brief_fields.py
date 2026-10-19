"""Extend projects with brief fields.

Revision ID: 026
Revises: 025
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026"
down_revision: Union[str, Sequence[str], None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("projects")]

    from sqlalchemy.dialects import postgresql

    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()

    if "product_goal" not in cols:
        op.add_column("projects", sa.Column("product_goal", sa.Text(), nullable=True))
    if "env_config" not in cols:
        op.add_column(
            "projects",
            sa.Column("env_config", json_type, server_default='{"target": "staging"}', nullable=False),
        )
    if "execution_limits" not in cols:
        op.add_column(
            "projects",
            sa.Column(
                "execution_limits",
                json_type,
                server_default='{"max_duration_seconds": 300, "max_agent_turns": 60, "max_retries": 3, "max_concurrent_executions": 2, "max_evidence_storage_mb": 500}',
                nullable=False,
            ),
        )
    if "safety_restrictions" not in cols:
        op.add_column(
            "projects",
            sa.Column(
                "safety_restrictions",
                json_type,
                server_default='{"production_access_allowed": false, "payment_actions_allowed": false, "account_deletion_allowed": false, "destructive_action_allowlist": [], "forbidden_routes": [], "forbidden_selectors": []}',
                nullable=False,
            ),
        )
    if "browser_settings" not in cols:
        op.add_column(
            "projects",
            sa.Column(
                "browser_settings",
                json_type,
                server_default='{"viewport_width": 1280, "viewport_height": 720, "locale": "en-US", "timezone": "America/New_York", "user_agent_override": null, "block_images": false}',
                nullable=False,
            ),
        )
    if "test_credentials_ref" not in cols:
        op.add_column(
            "projects",
            sa.Column("test_credentials_ref", sa.UUID(), nullable=True),
        )
        op.create_foreign_key(
            "fk_projects_test_credentials_ref_credentials",
            "projects",
            "credentials",
            ["test_credentials_ref"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_projects_test_credentials_ref",
            "projects",
            ["test_credentials_ref"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_projects_test_credentials_ref", table_name="projects")
    op.drop_constraint("fk_projects_test_credentials_ref_credentials", "projects", type_="foreignkey")
    op.drop_column("projects", "test_credentials_ref")
    op.drop_column("projects", "browser_settings")
    op.drop_column("projects", "safety_restrictions")
    op.drop_column("projects", "execution_limits")
    op.drop_column("projects", "env_config")
    op.drop_column("projects", "product_goal")
