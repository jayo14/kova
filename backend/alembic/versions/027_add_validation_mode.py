"""Add validation mode to flows and executions.

Revision ID: 027
Revises: 026
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027"
down_revision: Union[str, Sequence[str], None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    flow_cols = [c["name"] for c in insp.get_columns("flows")]
    if "mode" not in flow_cols:
        op.add_column(
            "flows",
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="functional"),
        )
        # Backfill existing flows: "regression" if goal_id is set, else "functional"
        op.execute("UPDATE flows SET mode = 'regression' WHERE goal_id IS NOT NULL")
        op.execute("UPDATE flows SET mode = 'functional' WHERE goal_id IS NULL")

    exec_cols = [c["name"] for c in insp.get_columns("executions")]
    if "mode" not in exec_cols:
        op.add_column(
            "executions",
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="regression"),
        )
        # Backfill existing executions: inherit from parent flow, or default to "regression"
        op.execute(
            """
            UPDATE executions
            SET mode = COALESCE(
                (SELECT flows.mode FROM flows WHERE flows.id = executions.flow_id),
                'regression'
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    exec_cols = [c["name"] for c in insp.get_columns("executions")]
    if "mode" in exec_cols:
        op.drop_column("executions", "mode")

    flow_cols = [c["name"] for c in insp.get_columns("flows")]
    if "mode" in flow_cols:
        op.drop_column("flows", "mode")
