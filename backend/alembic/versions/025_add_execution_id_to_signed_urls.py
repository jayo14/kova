"""Add execution_id to signed_urls table.

Revision ID: 025
Revises: 024
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025"
down_revision: Union[str, Sequence[str], None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns("signed_urls")]
    if "execution_id" not in cols:
        op.add_column(
            "signed_urls",
            sa.Column("execution_id", sa.UUID(), nullable=True),
        )
        op.create_foreign_key(
            "fk_signed_urls_execution_id_executions",
            "signed_urls",
            "executions",
            ["execution_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_index(
            "ix_signed_urls_execution_id",
            "signed_urls",
            ["execution_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_signed_urls_execution_id", table_name="signed_urls")
    op.drop_constraint("fk_signed_urls_execution_id_executions", "signed_urls", type_="foreignkey")
    op.drop_column("signed_urls", "execution_id")
