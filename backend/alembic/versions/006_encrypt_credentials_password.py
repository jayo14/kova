"""Widen password to Text and encrypt existing rows

Revision ID: 006
Revises: 7d26c7ea9a91
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "7d26c7ea9a91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("credentials") as batch_op:
        batch_op.alter_column(
            "password",
            existing_type=sa.String(255),
            type_=sa.Text(),
            nullable=False,
        )

    conn = op.get_bind()
    credentials_table = table(
        "credentials",
        column("id", sa.UUID),
        column("password", sa.Text),
    )
    rows = conn.execute(
        sa.select(credentials_table.c.id, credentials_table.c.password)
    ).fetchall()

    from app.modules.credentials.crypto import encrypt_credential, decrypt_credential

    for row in rows:
        cred_id, plain_pass = row[0], row[1]
        if plain_pass:
            try:
                decrypted = decrypt_credential(plain_pass)
                # If decrypt returns the same string and it doesn't look like a Fernet token, encrypt it
                if decrypted == plain_pass and not plain_pass.startswith("gAAAAA"):
                    enc = encrypt_credential(plain_pass)
                    conn.execute(
                        credentials_table.update()
                        .where(credentials_table.c.id == cred_id)
                        .values(password=enc)
                    )
            except Exception:
                enc = encrypt_credential(plain_pass)
                conn.execute(
                    credentials_table.update()
                    .where(credentials_table.c.id == cred_id)
                    .values(password=enc)
                )


def downgrade() -> None:
    conn = op.get_bind()
    credentials_table = table(
        "credentials",
        column("id", sa.UUID),
        column("password", sa.Text),
    )
    rows = conn.execute(
        sa.select(credentials_table.c.id, credentials_table.c.password)
    ).fetchall()

    from app.modules.credentials.crypto import decrypt_credential

    for row in rows:
        cred_id, cipher_pass = row[0], row[1]
        if cipher_pass:
            plain = decrypt_credential(cipher_pass)
            conn.execute(
                credentials_table.update()
                .where(credentials_table.c.id == cred_id)
                .values(password=plain[:255])
            )

    with op.batch_alter_table("credentials") as batch_op:
        batch_op.alter_column(
            "password",
            existing_type=sa.Text(),
            type_=sa.String(255),
            nullable=False,
        )
