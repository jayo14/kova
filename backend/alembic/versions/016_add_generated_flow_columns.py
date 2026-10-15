"""Add generated flow columns to flows table.

Revision ID: 016
Revises: 015
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "016"
down_revision: Union[str, Sequence[str], None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flows", sa.Column("source", sa.String(length=50), server_default="legacy", nullable=False))
    op.add_column("flows", sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False))
    op.add_column("flows", sa.Column("active", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("flows", sa.Column("json_repr", postgresql.JSON(astext_type=sa.Text()), nullable=True))
    op.add_column("flows", sa.Column("gherkin_repr", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("flows", "gherkin_repr")
    op.drop_column("flows", "json_repr")
    op.drop_column("flows", "active")
    op.drop_column("flows", "confidence")
    op.drop_column("flows", "source")
