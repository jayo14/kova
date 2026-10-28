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


def _migrate_password(raw_pass: str) -> str:
    """Convert plaintext or legacy Fernet ciphertext to the v1 format."""
    from app.modules.credentials.crypto import ENCRYPTION_PREFIX, encrypt_credential, get_fernet

    if raw_pass.startswith(ENCRYPTION_PREFIX):
        return raw_pass
    try:
        # Runtime decryption is strict; legacy recognition belongs only here.
        plaintext = get_fernet().decrypt(raw_pass.encode("utf-8")).decode("utf-8")
    except Exception:
        # Older installations could also contain plaintext values.
        plaintext = raw_pass
    return encrypt_credential(plaintext)


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

    from app.modules.credentials.crypto import ENCRYPTION_PREFIX

    for row in rows:
        cred_id, raw_pass = row[0], row[1]
        if raw_pass and not str(raw_pass).startswith(ENCRYPTION_PREFIX):
            enc = _migrate_password(str(raw_pass))
            conn.execute(
                credentials_table.update()
                .where(credentials_table.c.id == cred_id)
                .values(password=enc)
            )


def downgrade() -> None:
    pass
