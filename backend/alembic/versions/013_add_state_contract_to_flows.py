"""Add state_contract to flows.

Revision ID: 013
Revises: 012
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "013"
down_revision: Union[str, Sequence[str], None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flows", sa.Column("state_contract", postgresql.JSONB(), server_default="{}", nullable=True))


def downgrade() -> None:
    op.drop_column("flows", "state_contract")
