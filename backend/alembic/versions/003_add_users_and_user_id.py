"""add users table and user_id to projects

Revision ID: 003
Revises: 002
Create Date: 2025-01-03 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )

    # 2. Delete existing mock data (user requested clean slate)
    op.execute("DELETE FROM execution_events")
    op.execute("DELETE FROM executions")
    op.execute("DELETE FROM credentials")
    op.execute("DELETE FROM flows")
    op.execute("DELETE FROM projects")

    # 3. Add user_id to projects (NOT NULL since all data deleted)
    op.add_column(
        "projects",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # 4. Enable RLS on all tables
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE flows ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE executions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE execution_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE credentials ENABLE ROW LEVEL SECURITY")

    # 5. RLS policies: users can only access their own data
    op.execute(
        """
        CREATE POLICY users_own_data ON users
          FOR ALL USING (id = auth.uid())
        """
    )
    op.execute(
        """
        CREATE POLICY projects_own_data ON projects
          FOR ALL USING (user_id = auth.uid())
        """
    )
    op.execute(
        """
        CREATE POLICY flows_own_data ON flows
          FOR ALL USING (
            project_id IN (SELECT id FROM projects WHERE user_id = auth.uid())
          )
        """
    )
    op.execute(
        """
        CREATE POLICY executions_own_data ON executions
          FOR ALL USING (
            flow_id IN (
              SELECT f.id FROM flows f
              JOIN projects p ON f.project_id = p.id
              WHERE p.user_id = auth.uid()
            )
          )
        """
    )
    op.execute(
        """
        CREATE POLICY execution_events_own_data ON execution_events
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
    op.execute(
        """
        CREATE POLICY credentials_own_data ON credentials
          FOR ALL USING (
            project_id IN (SELECT id FROM projects WHERE user_id = auth.uid())
          )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS credentials_own_data ON credentials")
    op.execute("DROP POLICY IF EXISTS execution_events_own_data ON execution_events")
    op.execute("DROP POLICY IF EXISTS executions_own_data ON executions")
    op.execute("DROP POLICY IF EXISTS flows_own_data ON flows")
    op.execute("DROP POLICY IF EXISTS projects_own_data ON projects")
    op.execute("DROP POLICY IF EXISTS users_own_data ON users")

    op.execute("ALTER TABLE credentials DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE execution_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE executions DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE flows DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_column("projects", "user_id")
    op.drop_table("users")
