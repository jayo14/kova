"""Store explicit browser state requirements on flows."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, Sequence[str], None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("flows", sa.Column("preconditions", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("flows", "preconditions")
