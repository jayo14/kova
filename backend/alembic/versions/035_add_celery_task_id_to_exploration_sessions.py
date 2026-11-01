"""Add celery_task_id to exploration_sessions

Revision ID: 035
Revises: 8fb3c92be4ac
Create Date: 2026-11-01 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "035"
down_revision: Union[str, Sequence[str], None] = "8fb3c92be4ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add celery_task_id column to exploration_sessions."""
    op.add_column(
        "exploration_sessions",
        sa.Column("celery_task_id", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    """Remove celery_task_id column from exploration_sessions."""
    op.drop_column("exploration_sessions", "celery_task_id")
