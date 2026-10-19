"""Convert project JSON columns to JSONB on PostgreSQL.

Revision ID: 028
Revises: 027
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "028"
down_revision: Union[str, Sequence[str], None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        insp = sa.inspect(bind)
        cols = {c["name"]: c for c in insp.get_columns("projects")}
        target_cols = ["env_config", "execution_limits", "safety_restrictions", "browser_settings"]

        for col_name in target_cols:
            if col_name in cols:
                op.execute(
                    f"ALTER TABLE projects ALTER COLUMN {col_name} TYPE jsonb USING {col_name}::jsonb"
                )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        insp = sa.inspect(bind)
        cols = {c["name"]: c for c in insp.get_columns("projects")}
        target_cols = ["env_config", "execution_limits", "safety_restrictions", "browser_settings"]

        for col_name in target_cols:
            if col_name in cols:
                op.execute(
                    f"ALTER TABLE projects ALTER COLUMN {col_name} TYPE json USING {col_name}::json"
                )
