"""Extend evidence table with rich linked evidence columns.

Revision ID: 020
Revises: 019
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020"
down_revision: Union[str, Sequence[str], None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("dom_snapshot", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("a11y_tree", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("network_log", sa.JSON(), nullable=True))
    op.add_column("evidence", sa.Column("video_url", sa.String(length=1024), nullable=True))
    op.add_column("evidence", sa.Column("trace_url", sa.String(length=1024), nullable=True))
    op.add_column("evidence", sa.Column("element_locator", sa.String(length=500), nullable=True))
    op.add_column("evidence", sa.Column("timestamp_range", sa.JSON(), nullable=True))
    op.add_column("evidence", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence", "note")
    op.drop_column("evidence", "timestamp_range")
    op.drop_column("evidence", "element_locator")
    op.drop_column("evidence", "trace_url")
    op.drop_column("evidence", "video_url")
    op.drop_column("evidence", "network_log")
    op.drop_column("evidence", "a11y_tree")
    op.drop_column("evidence", "dom_snapshot")
