"""add tier field to organizations

Revision ID: 8fb3c92be4ac
Revises: 90c971bdbde7
Create Date: 2026-10-30 19:43:45.096008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8fb3c92be4ac'
down_revision: Union[str, Sequence[str], None] = '90c971bdbde7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The tier column is already added by revision 90c971bdbde7.
    # This revision is retained only to preserve the migration chain.
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
