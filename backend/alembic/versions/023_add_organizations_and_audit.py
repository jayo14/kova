"""Add organizations, quotas, project_members, audit_events tables and extend api_tokens with scopes.

Revision ID: 023
Revises: 022
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "023"
down_revision: Union[str, Sequence[str], None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("plan", sa.String(length=32), server_default="free", nullable=False),
        sa.Column("wrapped_dek", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_index("ix_organizations_owner_user_id", "organizations", ["owner_user_id"], unique=False)

    # 2. organization_members
    op.create_table(
        "organization_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="member", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_org_members_org_user", "organization_members", ["org_id", "user_id"], unique=True)

    # 3. organization_quotas
    op.create_table(
        "organization_quotas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("max_concurrent_executions", sa.Integer(), server_default="2", nullable=False),
        sa.Column("max_executions_per_day", sa.Integer(), server_default="50", nullable=False),
        sa.Column("max_product_graph_size", sa.Integer(), server_default="100", nullable=False),
        sa.Column("max_evidence_storage_mb", sa.Integer(), server_default="100", nullable=False),
        sa.Column("allowed_integrations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organization_quotas_org_id", "organization_quotas", ["org_id"], unique=True)

    # 4. project_members
    op.create_table(
        "project_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="viewer", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_members_project_user", "project_members", ["project_id", "user_id"], unique=True)

    # 5. audit_events
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_org_created", "audit_events", ["org_id", "created_at"], unique=False)
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"], unique=False)
    op.create_index("ix_audit_events_actor", "audit_events", ["actor_user_id"], unique=False)

    # 6. Add org_id to projects
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.UUID(), nullable=True))
        batch_op.create_foreign_key("fk_projects_org_id", "organizations", ["org_id"], ["id"], ondelete="SET NULL")

    # 7. Add scopes to api_tokens
    with op.batch_alter_table("api_tokens") as batch_op:
        batch_op.add_column(sa.Column("scopes", sa.JSON(), server_default='["*"]', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("api_tokens") as batch_op:
        batch_op.drop_column("scopes")

    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("fk_projects_org_id", type_="foreignkey")
        batch_op.drop_column("org_id")

    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_project_id", table_name="audit_events")
    op.drop_index("ix_audit_events_org_created", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_project_members_project_user", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("ix_organization_quotas_org_id", table_name="organization_quotas")
    op.drop_table("organization_quotas")

    op.drop_index("ix_org_members_org_user", table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index("ix_organizations_owner_user_id", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
