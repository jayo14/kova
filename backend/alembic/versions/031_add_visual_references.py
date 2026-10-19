"""Add visual_references table for visual validation mode.

Revision ID: 031
Revises: 030
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "031"
down_revision: Union[str, Sequence[str], None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    if "visual_references" not in tables:
        op.create_table(
            "visual_references",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("flow_id", sa.Uuid(), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
            sa.Column("screenshot_url", sa.Text(), nullable=False),
            sa.Column("a11y_tree", json_type, nullable=False, server_default="{}"),
            sa.Column("viewport", json_type, nullable=False, server_default="{}"),
            sa.Column("label", sa.String(length=255), nullable=False, server_default="Baseline"),
            sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_visual_references_flow_id", "visual_references", ["flow_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "visual_references" in tables:
        op.drop_index("ix_visual_references_flow_id", table_name="visual_references")
        op.drop_table("visual_references")
