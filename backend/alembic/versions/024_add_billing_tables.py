"""Add subscriptions, invoices, usage_events tables and onboarding_step to users.

Revision ID: 024
Revises: 023
"""

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024"
down_revision: Union[str, Sequence[str], None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add onboarding_step to users table
    bind = op.get_bind()
    insp = sa.inspect(bind)
    user_cols = [c["name"] for c in insp.get_columns("users")]
    if "onboarding_step" not in user_cols:
        op.add_column(
            "users",
            sa.Column("onboarding_step", sa.Integer(), server_default="0", nullable=False),
        )

    # 2. subscriptions table
    if not insp.has_table("subscriptions"):
        op.create_table(
            "subscriptions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("org_id", sa.UUID(), nullable=False),
            sa.Column("plan", sa.String(length=32), server_default="free", nullable=False),
            sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
            sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
            sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_subscriptions_org_id", "subscriptions", ["org_id"], unique=True)
        op.create_index(
            "ix_subscriptions_stripe_sub_id",
            "subscriptions",
            ["stripe_subscription_id"],
        )

    # 3. invoices table
    if not insp.has_table("invoices"):
        op.create_table(
            "invoices",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("org_id", sa.UUID(), nullable=False),
            sa.Column("stripe_invoice_id", sa.String(length=255), nullable=False),
            sa.Column("amount_due", sa.Integer(), server_default="0", nullable=False),
            sa.Column("amount_paid", sa.Integer(), server_default="0", nullable=False),
            sa.Column("currency", sa.String(length=8), server_default="usd", nullable=False),
            sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
            sa.Column("hosted_invoice_url", sa.String(length=1024), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_invoices_org_id", "invoices", ["org_id"])
        op.create_index("ix_invoices_stripe_id", "invoices", ["stripe_invoice_id"], unique=True)

    # 4. usage_events table
    if not insp.has_table("usage_events"):
        op.create_table(
            "usage_events",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("org_id", sa.UUID(), nullable=False),
            sa.Column("execution_id", sa.UUID(), nullable=True),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("plan_at_time", sa.String(length=32), server_default="free", nullable=False),
            sa.Column("storage_bytes", sa.BigInteger(), server_default="0", nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_usage_events_org_id", "usage_events", ["org_id"])
        op.create_index("ix_usage_events_execution_id", "usage_events", ["execution_id"])
        op.create_index("ix_usage_events_timestamp", "usage_events", ["timestamp"])


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_table("invoices")
    op.drop_table("subscriptions")
    op.drop_column("users", "onboarding_step")
