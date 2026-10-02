"""Unit tests for credential model and schemas."""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.credentials.schemas import CredentialCreate, CredentialRead


class TestCredentialCreateSchema:
    def test_valid_credential(self):
        cred = CredentialCreate(
            name="login",
            email="user@example.com",
            password="secret123",
        )
        assert cred.name == "login"
        assert cred.email == "user@example.com"
        assert cred.password == "secret123"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            CredentialCreate(name="", email="u@e.com", password="pass")

    def test_empty_email_rejected(self):
        with pytest.raises(ValidationError):
            CredentialCreate(name="login", email="", password="pass")

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            CredentialCreate(name="login", email="u@e.com", password="")


class TestCredentialReadSchema:
    def test_read_excludes_password(self):
        data = {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "name": "login",
            "email": "user@example.com",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        cred = CredentialRead(**data)
        cred_dict = cred.model_dump()
        assert "password" not in cred_dict
        assert cred_dict["name"] == "login"
        assert cred_dict["email"] == "user@example.com"
