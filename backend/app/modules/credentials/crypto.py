"""Fernet symmetric encryption for stored credentials."""

import base64
from cryptography.fernet import Fernet, InvalidToken
from app.config.settings import settings

import os
import sys

# Deterministic test fallback key (32 bytes base64-encoded)
_DEV_FERNET_KEY = b"k9_8TqZfUvYx3W1eR7tL5mN2pQ4sA6dF8gH0jK2lM4o="


ENCRYPTION_PREFIX = "v1:enc:"
LEGACY_FERNET_PREFIX = "gAAAAA"


def get_fernet() -> Fernet:
    key_str = settings.CREDENTIAL_ENCRYPTION_KEY
    if key_str and key_str.strip():
        key_bytes = key_str.strip().encode("utf-8")
        try:
            decoded = base64.b64decode(key_bytes, altchars=b"-_", validate=True)
            if len(decoded) != 32:
                raise ValueError
            return Fernet(key_bytes)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "CREDENTIAL_ENCRYPTION_KEY must be a valid 32-byte url-safe base64 Fernet key."
            ) from exc

    # Hardcoded dev key allowed in test and development environments
    if (
        "pytest" in sys.modules
        or os.environ.get("PYTEST_CURRENT_TEST")
        or settings.ENVIRONMENT in ("test", "development")
        or not settings.is_production
    ):
        return Fernet(_DEV_FERNET_KEY)

    raise ValueError("CREDENTIAL_ENCRYPTION_KEY is required and must be configured outside tests.")


def encrypt_credential(plain_text: str) -> str:
    """Encrypt a plaintext credential string using versioned Fernet format."""
    if not plain_text:
        return plain_text
    f = get_fernet()
    token = f.encrypt(plain_text.encode("utf-8")).decode("utf-8")
    return f"{ENCRYPTION_PREFIX}{token}"


def decrypt_credential(cipher_text: str) -> str:
    """Decrypt a versioned Fernet-encrypted credential string.

    Fails closed: raises InvalidToken if token is unencrypted or cannot be decrypted.
    """
    if not cipher_text:
        return cipher_text

    if cipher_text.startswith(ENCRYPTION_PREFIX):
        raw_token = cipher_text[len(ENCRYPTION_PREFIX):]
    elif cipher_text.startswith("v1:"):
        raw_token = cipher_text[len("v1:"):]
    elif cipher_text.startswith(LEGACY_FERNET_PREFIX):
        raw_token = cipher_text
    else:
        raise InvalidToken("Credential is not stored in an encrypted format")

    f = get_fernet()
    return f.decrypt(raw_token.encode("utf-8")).decode("utf-8")


def is_encrypted_credential(value: str) -> bool:
    """Check if a string matches versioned or legacy encrypted credential formats."""
    if not value or not isinstance(value, str):
        return False
    return (
        value.startswith(ENCRYPTION_PREFIX)
        or value.startswith("v1:")
        or value.startswith(LEGACY_FERNET_PREFIX)
    )
