"""Credential models for secure handling.

Credentials are never stored in flow steps directly.
Flows reference credentials by ID.
"""

from dataclasses import dataclass


@dataclass
class Credential:
    """A credential pair (email + password).

    Attributes:
        id: Unique identifier for this credential.
        email: The email/username.
        password: The password (never logged or persisted in payloads).
    """

    id: str
    email: str
    password: str

    def to_safe_dict(self) -> dict:
        """Convert to dict with password masked.

        Safe for logging and event payloads.
        """
        return {
            "id": self.id,
            "email": self.email,
            "password": "****",
        }

    def __repr__(self) -> str:
        return f"Credential(id={self.id!r}, email={self.email!r}, password=****)"

    def __str__(self) -> str:
        return self.__repr__()

    def get_password(self) -> str:
        """Access the password directly.

        Use sparingly — only inside execution context.
        """
        return self.password


class CredentialNotFoundError(Exception):
    """Raised when a referenced credential ID is not found."""

    def __init__(self, credential_id: str):
        self.credential_id = credential_id
        super().__init__(f"Credential not found: {credential_id}")
