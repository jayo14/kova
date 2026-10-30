"""add tier field to organizations

Revision ID: 90c971bdbde7
Revises: 034
Create Date: 2026-10-30 19:43:29.910918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90c971bdbde7'
down_revision: Union[str, Sequence[str], None] = '034'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "organizations",
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("organizations", "tier")