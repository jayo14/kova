"""In-memory credential store for local development.

Simplest safe mechanism: holds credentials in memory,
never persists to disk, never logs passwords.
"""

import logging
from typing import Any

from app.engine.credentials.models import Credential, CredentialNotFoundError

logger = logging.getLogger(__name__)


class CredentialStore:
    """In-memory credential storage.

    For local development. Credentials are held in memory only.
    Never logs passwords. Never serializes passwords.

    Usage:
        store = CredentialStore()
        store.add(Credential(id="login", email="user@example.com", password="secret"))
        cred = store.get("login")
    """

    def __init__(self):
        self._credentials: dict[str, Credential] = {}

    def add(self, credential: Credential) -> None:
        """Add a credential to the store.

        Args:
            credential: The credential to store.

        Raises:
            ValueError: If credential ID is empty.
        """
        if not credential.id:
            raise ValueError("Credential ID cannot be empty")

        self._credentials[credential.id] = credential
        logger.debug("Credential added: %s", credential.id)

    def get(self, credential_id: str) -> Credential:
        """Get a credential by ID.

        Args:
            credential_id: The credential ID to look up.

        Returns:
            The matching Credential.

        Raises:
            CredentialNotFoundError: If no credential with this ID exists.
        """
        if credential_id not in self._credentials:
            raise CredentialNotFoundError(credential_id)
        return self._credentials[credential_id]

    def has(self, credential_id: str) -> bool:
        """Check if a credential exists."""
        return credential_id in self._credentials

    def remove(self, credential_id: str) -> bool:
        """Remove a credential by ID.

        Returns:
            True if removed, False if not found.
        """
        if credential_id in self._credentials:
            del self._credentials[credential_id]
            logger.debug("Credential removed: %s", credential_id)
            return True
        return False

    def list_ids(self) -> list[str]:
        """List all credential IDs (never returns passwords)."""
        return list(self._credentials.keys())

    def clear(self) -> None:
        """Remove all credentials."""
        self._credentials.clear()
        logger.debug("Credential store cleared")

    def to_safe_dict(self) -> dict[str, dict]:
        """Export credentials with passwords masked.

        Safe for debugging and event payloads.
        """
        return {cid: cred.to_safe_dict() for cid, cred in self._credentials.items()}


def create_credential_from_flow_step(step: dict) -> str | None:
    """Extract credential_id from a flow step.

    Returns the credential_id if present, None otherwise.
    """
    return step.get("credential_id")
