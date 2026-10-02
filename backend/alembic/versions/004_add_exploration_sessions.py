"""add exploration sessions and events tables

Revision ID: 004
Revises: 003
Create Date: 2026-09-16 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exploration_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=50),
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column("selected_role", sa.String(length=100), nullable=True),
        sa.Column(
            "discoveries", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "candidate_missions",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("question", postgresql.JSONB(), nullable=True),
        sa.Column("credential_request", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exploration_sessions")),
    )
    op.create_index(
        "ix_exploration_sessions_user_id", "exploration_sessions", ["user_id"]
    )
    op.create_index(
        "ix_exploration_sessions_status", "exploration_sessions", ["status"]
    )
    op.create_index(
        "ix_exploration_sessions_project_id",
        "exploration_sessions",
        ["project_id"],
    )

    op.create_table(
        "exploration_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "exploration_id",
            sa.Uuid(),
            sa.ForeignKey("exploration_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exploration_events")),
    )
    op.create_index(
        "ix_exploration_events_exploration_id",
        "exploration_events",
        ["exploration_id"],
    )
    op.create_index(
        "ix_exploration_events_created_at",
        "exploration_events",
        ["created_at"],
    )

    # Enable RLS
    op.execute("ALTER TABLE exploration_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE exploration_events ENABLE ROW LEVEL SECURITY")

    # RLS Policies
    op.execute(
        """
        CREATE POLICY exploration_sessions_own_data ON exploration_sessions
          FOR ALL USING (user_id = auth.uid())
        """
    )
    op.execute(
        """
        CREATE POLICY exploration_events_own_data ON exploration_events
          FOR ALL USING (
            exploration_id IN (
              SELECT id FROM exploration_sessions WHERE user_id = auth.uid()
            )
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS exploration_events_own_data ON exploration_events")
    op.execute("DROP POLICY IF EXISTS exploration_sessions_own_data ON exploration_sessions")
    op.execute("ALTER TABLE exploration_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE exploration_sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("exploration_events")
    op.drop_table("exploration_sessions")
