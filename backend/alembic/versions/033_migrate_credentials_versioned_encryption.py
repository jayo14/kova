"""Migrate credentials to versioned encryption format (v1:enc:)

Revision ID: 033
Revises: 032
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision: str = "033"
down_revision: Union[str, Sequence[str], None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()
    if "credentials" not in tables:
        return

    credentials_table = table(
        "credentials",
        column("id", sa.UUID),
        column("password", sa.Text),
    )
    rows = conn.execute(
        sa.select(credentials_table.c.id, credentials_table.c.password)
    ).fetchall()

    from app.modules.credentials.crypto import encrypt_credential, ENCRYPTION_PREFIX, get_fernet

    for row in rows:
        cred_id, raw_pass = row[0], row[1]
        if raw_pass and not str(raw_pass).startswith(ENCRYPTION_PREFIX):
            value = str(raw_pass)
            # Legacy Fernet tokens must decrypt successfully before migration;
            # malformed ciphertext is never reinterpreted as a plaintext secret.
            if value.startswith("gAAAA"):
                value = get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
            enc = encrypt_credential(value)
            conn.execute(
                credentials_table.update()
                .where(credentials_table.c.id == cred_id)
                .values(password=enc)
            )


def downgrade() -> None:
    pass
