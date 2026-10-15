"""Add purpose and step_id to evidence.

Revision ID: 014
Revises: 013
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, Sequence[str], None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("purpose", sa.String(length=50), server_default="legacy", nullable=False))
    op.add_column("evidence", sa.Column("step_id", sa.String(length=100), nullable=True))
    op.create_index("ix_evidence_purpose", "evidence", ["purpose"])
    op.create_index("ix_evidence_step_id", "evidence", ["step_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_step_id", table_name="evidence")
    op.drop_index("ix_evidence_purpose", table_name="evidence")
    op.drop_column("evidence", "step_id")
    op.drop_column("evidence", "purpose")
