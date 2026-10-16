from __future__ import annotations

import logging
from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings
from app.modules.credentials.crypto import encrypt_credential, decrypt_credential
from app.modules.organizations.models import Organization

logger = logging.getLogger(__name__)


def generate_org_dek() -> str:
    """Generate a high-entropy Fernet 256-bit encryption key."""
    return Fernet.generate_key().decode("utf-8")


def wrap_dek(dek: str) -> str:
    """Wrap (encrypt) the per-organization DEK with the master KMS/Fernet key."""
    return encrypt_credential(dek)


def unwrap_dek(wrapped_dek: str) -> str:
    """Unwrap (decrypt) the per-organization DEK using the master key."""
    return decrypt_credential(wrapped_dek)


def encrypt_with_org_dek(org: Organization, plaintext: str) -> str:
    """Encrypt sensitive tenant data using organization's dedicated DEK."""
    if not org.wrapped_dek:
        # If enterprise org hasn't initialized DEK, generate and wrap it
        raw_dek = generate_org_dek()
        org.wrapped_dek = wrap_dek(raw_dek)

    raw_dek = unwrap_dek(org.wrapped_dek)
    f = Fernet(raw_dek.encode("utf-8"))
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_with_org_dek(org: Organization, ciphertext: str) -> str:
    """Decrypt sensitive tenant data using organization's dedicated DEK."""
    if not org.wrapped_dek:
        raise ValueError("Organization does not have a wrapped DEK configured")

    raw_dek = unwrap_dek(org.wrapped_dek)
    f = Fernet(raw_dek.encode("utf-8"))
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
