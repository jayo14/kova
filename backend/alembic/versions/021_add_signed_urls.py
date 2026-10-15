"""Add signed_urls table for persisted, revocable validation report URLs.

Revision ID: 021
Revises: 020
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "021"
down_revision: Union[str, Sequence[str], None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signed_urls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("validation_id", sa.UUID(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("signature", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["validation_id"], ["validation_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signed_urls_validation_id", "signed_urls", ["validation_id"], unique=False)
    op.create_index("ix_signed_urls_url", "signed_urls", ["url"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_signed_urls_url", table_name="signed_urls")
    op.drop_index("ix_signed_urls_validation_id", table_name="signed_urls")
    op.drop_table("signed_urls")
