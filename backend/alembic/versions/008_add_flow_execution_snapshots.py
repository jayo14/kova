"""Version flows and preserve the exact definition used by each run."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "008"
down_revision: Union[str, Sequence[str], None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flows", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("executions", sa.Column("flow_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("executions", sa.Column("flow_snapshot", postgresql.JSONB(), server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("executions", "flow_snapshot")
    op.drop_column("executions", "flow_version")
    op.drop_column("flows", "version")
