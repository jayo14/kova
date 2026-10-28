"""Tests for one-way migration of plaintext and legacy Fernet credentials."""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from cryptography.fernet import InvalidToken

from app.modules.credentials.crypto import (
    decrypt_credential,
    encrypt_credential,
    get_fernet,
)


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "033_migrate_credentials_versioned_encryption.py"
    )
    spec = importlib.util.spec_from_file_location("credential_migration_033", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _credential_table(connection):
    table = sa.Table(
        "credentials",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("password", sa.Text()),
    )
    table.create(connection)
    return table


def test_migration_encrypts_plaintext_and_wraps_legacy_fernet(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        table = _credential_table(connection)
        plain_id, legacy_id = uuid.uuid4(), uuid.uuid4()
        legacy_token = get_fernet().encrypt(b"old-secret").decode()
        connection.execute(table.insert(), [
            {"id": plain_id, "password": "plain-secret"},
            {"id": legacy_id, "password": legacy_token},
        ])
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        migration.upgrade()

        rows = dict(connection.execute(sa.select(table.c.id, table.c.password)).all())
        assert decrypt_credential(rows[plain_id]) == "plain-secret"
        assert decrypt_credential(rows[legacy_id]) == "old-secret"
    engine.dispose()


def test_migration_rejects_malformed_legacy_ciphertext(monkeypatch):
    migration = _load_migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        table = _credential_table(connection)
        row_id = uuid.uuid4()
        connection.execute(table.insert(), {"id": row_id, "password": "gAAAA-invalid"})
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

        with pytest.raises(InvalidToken):
            migration.upgrade()
    engine.dispose()
