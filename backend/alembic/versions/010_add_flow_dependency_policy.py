"""Add reusable flow dependencies and repeatability policy."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, Sequence[str], None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flows", sa.Column("dependencies", postgresql.JSONB(), server_default="[]", nullable=False))
    op.add_column("flows", sa.Column("provides_capabilities", postgresql.JSONB(), server_default="[]", nullable=False))
    op.add_column("flows", sa.Column("repeatability", sa.String(length=32), server_default="repeatable", nullable=False))
    op.add_column("flows", sa.Column("reset_strategy", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("flows", "reset_strategy")
    op.drop_column("flows", "repeatability")
    op.drop_column("flows", "provides_capabilities")
    op.drop_column("flows", "dependencies")
