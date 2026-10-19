"""Add provenance and Goal epistemic fields to Product Graph tables.

Revision ID: 030
Revises: 029
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "030"
down_revision: Union[str, Sequence[str], None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()

    # 1. Product Goals
    goal_cols = [c["name"] for c in insp.get_columns("product_goals")]
    if "provenance" not in goal_cols:
        op.add_column("product_goals", sa.Column("provenance", sa.String(length=32), nullable=False, server_default="inferred"))
        op.execute("UPDATE product_goals SET provenance = 'inferred' WHERE source = 'ai_proposal'")
        op.execute("UPDATE product_goals SET provenance = 'expected' WHERE source = 'user_provided'")
        op.execute("UPDATE product_goals SET provenance = 'observed' WHERE source NOT IN ('ai_proposal', 'user_provided')")

    if "business_rules" not in goal_cols:
        op.add_column("product_goals", sa.Column("business_rules", json_type, nullable=False, server_default="[]"))
    if "negative_scenarios" not in goal_cols:
        op.add_column("product_goals", sa.Column("negative_scenarios", json_type, nullable=False, server_default="[]"))
    if "acceptance_criteria" not in goal_cols:
        op.add_column("product_goals", sa.Column("acceptance_criteria", json_type, nullable=False, server_default="[]"))
    if "unknowns" not in goal_cols:
        op.add_column("product_goals", sa.Column("unknowns", json_type, nullable=False, server_default="[]"))

    # 2. Other entity tables get provenance
    tables = [
        "product_personas",
        "product_pages",
        "product_actions",
        "product_capabilities",
        "product_states",
        "product_invariants",
    ]
    for table_name in tables:
        cols = [c["name"] for c in insp.get_columns(table_name)]
        if "provenance" not in cols:
            op.add_column(table_name, sa.Column("provenance", sa.String(length=32), nullable=False, server_default="observed"))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    tables = [
        "product_personas",
        "product_pages",
        "product_actions",
        "product_capabilities",
        "product_states",
        "product_invariants",
    ]
    for table_name in tables:
        cols = [c["name"] for c in insp.get_columns(table_name)]
        if "provenance" in cols:
            op.drop_column(table_name, "provenance")

    goal_cols = [c["name"] for c in insp.get_columns("product_goals")]
    for col in ("unknowns", "acceptance_criteria", "negative_scenarios", "business_rules", "provenance"):
        if col in goal_cols:
            op.drop_column("product_goals", col)
