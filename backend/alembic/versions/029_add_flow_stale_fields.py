"""Add stale reason, requires review, and last validated graph version to flows.

Revision ID: 029
Revises: 028
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "029"
down_revision: Union[str, Sequence[str], None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    flow_cols = [c["name"] for c in insp.get_columns("flows")]
    if "stale_reason" not in flow_cols:
        op.add_column("flows", sa.Column("stale_reason", sa.Text(), nullable=True))
    if "requires_review" not in flow_cols:
        op.add_column("flows", sa.Column("requires_review", sa.Boolean(), nullable=False, server_default="false"))
    if "last_validated_against_graph_version" not in flow_cols:
        op.add_column("flows", sa.Column("last_validated_against_graph_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    flow_cols = [c["name"] for c in insp.get_columns("flows")]
    if "last_validated_against_graph_version" in flow_cols:
        op.drop_column("flows", "last_validated_against_graph_version")
    if "requires_review" in flow_cols:
        op.drop_column("flows", "requires_review")
    if "stale_reason" in flow_cols:
        op.drop_column("flows", "stale_reason")
