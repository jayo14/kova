"""Add persona and auth_strategy to credentials table.

Revision ID: 017
Revises: 016
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017"
down_revision: Union[str, Sequence[str], None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("credentials", sa.Column("persona", sa.String(length=128), nullable=True))
    op.add_column(
        "credentials",
        sa.Column("auth_strategy", sa.String(length=64), server_default="password_form", nullable=True),
    )


def downgrade() -> None:
    op.drop_column("credentials", "auth_strategy")
    op.drop_column("credentials", "persona")
