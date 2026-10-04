"""Fernet symmetric encryption for stored credentials."""

import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from app.config.settings import settings

# Deterministic dev/test fallback key (32 bytes base64-encoded)
_DEV_FERNET_KEY = b"k9_8TqZfUvYx3W1eR7tL5mN2pQ4sA6dF8gH0jK2lM4o="


def get_fernet() -> Fernet:
    key_str = settings.CREDENTIAL_ENCRYPTION_KEY
    if key_str and key_str.strip():
        key_bytes = key_str.strip().encode("utf-8")
        try:
            decoded = base64.urlsafe_b64decode(key_bytes)
            if len(decoded) == 32:
                return Fernet(key_bytes)
        except Exception:
            pass
        derived = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
        return Fernet(derived)

    return Fernet(_DEV_FERNET_KEY)


def encrypt_credential(plain_text: str) -> str:
    """Encrypt a plaintext credential string using Fernet."""
    if not plain_text:
        return plain_text
    f = get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_credential(cipher_text: str) -> str:
    """Decrypt a Fernet-encrypted credential string."""
    if not cipher_text:
        return cipher_text
    try:
        f = get_fernet()
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        # Fallback if plaintext or invalid token
        return cipher_text
