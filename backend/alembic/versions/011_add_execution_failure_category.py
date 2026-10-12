"""Persist execution failure classification separately from status."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, Sequence[str], None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("failure_category", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("executions", "failure_category")
