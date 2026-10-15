"""Add planning and prerequisite states to executions.

Revision ID: 018
Revises: 017
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, Sequence[str], None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # executions.status is a VARCHAR(50) column with no DB-level check constraint.
    # New statuses (PLANNING, RESOLVING_PREREQUISITES, PREREQUISITE_FAILED, CONTAMINATION_DETECTED)
    # are recognized by SQLAlchemy and application state machines.
    pass


def downgrade() -> None:
    pass
