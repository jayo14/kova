"""Add exploration budget fields to exploration_sessions

Revision ID: 034
Revises: 033
Create Date: 2026-10-28 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "034"
down_revision: Union[str, Sequence[str], None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add budget tracking columns to exploration_sessions."""
    op.add_column(
        "exploration_sessions",
        sa.Column("budget_used", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "exploration_sessions",
        sa.Column("budget_cutoff", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove budget tracking columns from exploration_sessions."""
    op.drop_column("exploration_sessions", "budget_cutoff")
    op.drop_column("exploration_sessions", "budget_used")
