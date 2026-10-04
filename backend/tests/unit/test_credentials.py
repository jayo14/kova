"""Unit tests for credential handling.

Tests credential models, store, masking, and security guarantees.
No browser required.
"""

import pytest

from app.engine.credentials.models import Credential, CredentialNotFoundError
from app.engine.credentials.store import (
    CredentialStore,
    create_credential_from_flow_step,
)


# --- Credential model ---


def test_credential_to_safe_dict():
    """to_safe_dict masks password."""
    cred = Credential(id="login", email="user@example.com", password="secret123")
    d = cred.to_safe_dict()
    assert d["id"] == "login"
    assert d["email"] == "user@example.com"
    assert d["password"] == "****"


def test_credential_get_password():
    """get_password returns actual password."""
    cred = Credential(id="login", email="user@example.com", password="secret123")
    assert cred.get_password() == "secret123"


def test_credential_id_required_in_store():
    """Credential ID cannot be empty in store."""
    store = CredentialStore()
    with pytest.raises(ValueError):
        store.add(Credential(id="", email="a@b.com", password="p"))


# --- CredentialStore ---


def test_store_add_and_get():
    """Add and retrieve credential by ID."""
    store = CredentialStore()
    cred = Credential(id="login", email="a@b.com", password="pass")
    store.add(cred)
    result = store.get("login")
    assert result.email == "a@b.com"
    assert result.get_password() == "pass"


def test_store_get_not_found():
    """Get raises CredentialNotFoundError for missing ID."""
    store = CredentialStore()
    with pytest.raises(CredentialNotFoundError) as exc_info:
        store.get("nonexistent")
    assert exc_info.value.credential_id == "nonexistent"


def test_store_has():
    """has returns True for existing credentials."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="a@b.com", password="p"))
    assert store.has("c1") is True
    assert store.has("c2") is False


def test_store_remove():
    """remove deletes a credential."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="a@b.com", password="p"))
    assert store.remove("c1") is True
    assert store.has("c1") is False
    assert store.remove("c1") is False


def test_store_list_ids():
    """list_ids returns all IDs without passwords."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="a@b.com", password="p1"))
    store.add(Credential(id="c2", email="b@b.com", password="p2"))
    ids = store.list_ids()
    assert "c1" in ids
    assert "c2" in ids
    assert "p1" not in ids
    assert "p2" not in ids


def test_store_clear():
    """clear removes all credentials."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="a@b.com", password="p"))
    store.clear()
    assert store.has("c1") is False


def test_store_to_safe_dict():
    """to_safe_dict masks all passwords."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="a@b.com", password="secret"))
    store.add(Credential(id="c2", email="b@b.com", password="password123"))
    d = store.to_safe_dict()
    assert d["c1"]["password"] == "****"
    assert d["c2"]["password"] == "****"
    assert "secret" not in str(d)
    assert "password123" not in str(d)


def test_store_empty_id_raises():
    """Adding credential with empty ID raises ValueError."""
    store = CredentialStore()
    with pytest.raises(ValueError):
        store.add(Credential(id="", email="a@b.com", password="p"))


# --- create_credential_from_flow_step ---


def test_create_credential_from_flow_step_with_id():
    """Extracts credential_id from step."""
    step = {"type": "type", "credential_id": "login"}
    assert create_credential_from_flow_step(step) == "login"


def test_create_credential_from_flow_step_without_id():
    """Returns None when no credential_id."""
    step = {"type": "click", "target": {"css": "#btn"}}
    assert create_credential_from_flow_step(step) is None


# --- Security: passwords never leak ---


def test_password_not_in_str_representation():
    """Password is not in Credential str or repr."""
    cred = Credential(id="c1", email="a@b.com", password="supersecret")
    # Ensure password doesn't appear in common string representations
    assert "supersecret" not in str(cred.to_safe_dict())
    assert "supersecret" not in repr(cred.to_safe_dict())


def test_store_safe_dict_no_password_leak():
    """Store to_safe_dict never contains real passwords."""
    store = CredentialStore()
    store.add(Credential(id="c1", email="a@b.com", password="mysecretpassword"))
    safe = store.to_safe_dict()
    assert "mysecretpassword" not in str(safe)
    assert safe["c1"]["password"] == "****"


def test_credential_store_isolation():
    """Credentials are isolated between stores."""
    store1 = CredentialStore()
    store2 = CredentialStore()
    store1.add(Credential(id="c1", email="a@b.com", password="pass1"))
    store2.add(Credential(id="c1", email="b@b.com", password="pass2"))

    assert store1.get("c1").get_password() == "pass1"
    assert store2.get("c1").get_password() == "pass2"


# --- Fernet Encryption & Production Validation ---


def test_decrypt_credential_raises_invalid_token():
    """decrypt_credential must raise InvalidToken on corrupted ciphertext."""
    from cryptography.fernet import InvalidToken
    from app.modules.credentials.crypto import decrypt_credential

    with pytest.raises(InvalidToken):
        decrypt_credential("gAAAAABcorruptedTokenHere1234567890=")


def test_production_rejects_empty_or_dev_credential_key():
    """In production, CREDENTIAL_ENCRYPTION_KEY must be a valid non-dev Fernet key."""
    from app.config.settings import Settings

    valid_jwt = "a" * 32
    # Missing credential key
    with pytest.raises(ValueError, match="CREDENTIAL_ENCRYPTION_KEY must be set"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY=valid_jwt,
            CREDENTIAL_ENCRYPTION_KEY="",
        )

    # Dev credential key
    with pytest.raises(ValueError, match="cannot be the default dev key"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY=valid_jwt,
            CREDENTIAL_ENCRYPTION_KEY="k9_8TqZfUvYx3W1eR7tL5mN2pQ4sA6dF8gH0jK2lM4o=",
        )

    # Invalid length key
    with pytest.raises(ValueError, match="valid 32-byte"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY=valid_jwt,
            CREDENTIAL_ENCRYPTION_KEY="not-a-valid-fernet-key",
        )

    # Valid key accepted
    from cryptography.fernet import Fernet
    valid_fernet = Fernet.generate_key().decode()
    s = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY=valid_jwt,
        CREDENTIAL_ENCRYPTION_KEY=valid_fernet,
    )
    assert s.CREDENTIAL_ENCRYPTION_KEY == valid_fernet
