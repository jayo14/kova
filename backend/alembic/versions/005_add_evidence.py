"""add evidence table

Revision ID: 005
Revises: 004
Create Date: 2026-09-16 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "execution_id",
            sa.Uuid(),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="CAPTURED",
        ),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
    )
    op.create_index(
        "ix_evidence_execution_id", "evidence", ["execution_id"]
    )
    op.create_index(
        "ix_evidence_type", "evidence", ["type"]
    )

    # Enable RLS
    op.execute("ALTER TABLE evidence ENABLE ROW LEVEL SECURITY")

    # RLS Policies — evidence accessible via execution → flow → project → user chain
    op.execute(
        """
        CREATE POLICY evidence_own_data ON evidence
          FOR ALL USING (
            execution_id IN (
              SELECT e.id FROM executions e
              JOIN flows f ON e.flow_id = f.id
              JOIN projects p ON f.project_id = p.id
              WHERE p.user_id = auth.uid()
            )
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS evidence_own_data ON evidence")
    op.execute("ALTER TABLE evidence DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_evidence_type", table_name="evidence")
    op.drop_index("ix_evidence_execution_id", table_name="evidence")
    op.drop_table("evidence")
