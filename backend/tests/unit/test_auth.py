import uuid
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClientError
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User


@pytest.fixture
def ec_key_pair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def mock_signing_key(ec_key_pair):
    _, public_key = ec_key_pair
    mock_key = MagicMock()
    mock_key.key = public_key
    return mock_key


def _auth_payload(**overrides) -> dict:
    """Build a Supabase-shaped JWT payload including required iss claim."""
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "exp": 9999999999,
        "email": "test@example.com",
        "user_metadata": {"name": "Test User"},
        "iss": settings.effective_jwt_issuer
        or "https://zmbhiudolgnlccdqicas.supabase.co/auth/v1",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_get_current_user_valid_token(db_session: AsyncSession, ec_key_pair, mock_signing_key):
    private_key, _ = ec_key_pair
    user_id = uuid.uuid4()
    payload = _auth_payload(
        sub=str(user_id),
        user_metadata={"name": "Test User"},
    )
    token = jwt.encode(payload, private_key, algorithm="ES256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_getter.return_value = mock_client

        user = await get_current_user(credentials=credentials, db=db_session)

    assert isinstance(user, User)
    assert user.id == user_id
    assert user.email == "test@example.com"
    assert user.name == "Test User"


@pytest.mark.asyncio
async def test_get_current_user_full_name_fallback(db_session: AsyncSession, ec_key_pair, mock_signing_key):
    private_key, _ = ec_key_pair
    user_id = uuid.uuid4()
    payload = _auth_payload(
        sub=str(user_id),
        email="fullname@example.com",
        user_metadata={"full_name": "Full Name User"},
    )
    token = jwt.encode(payload, private_key, algorithm="ES256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_getter.return_value = mock_client

        user = await get_current_user(credentials=credentials, db=db_session)

    assert user.id == user_id
    assert user.name == "Full Name User"


@pytest.mark.asyncio
async def test_get_current_user_expired_token(db_session: AsyncSession, ec_key_pair, mock_signing_key):
    private_key, _ = ec_key_pair
    payload = _auth_payload(exp=1000000000)  # in the past
    token = jwt.encode(payload, private_key, algorithm="ES256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_getter.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token has expired"


@pytest.mark.asyncio
async def test_get_current_user_invalid_audience(db_session: AsyncSession, ec_key_pair, mock_signing_key):
    private_key, _ = ec_key_pair
    payload = _auth_payload(aud="wrong_audience")
    token = jwt.encode(payload, private_key, algorithm="ES256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_getter.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"


@pytest.mark.asyncio
async def test_get_current_user_missing_sub(db_session: AsyncSession, ec_key_pair, mock_signing_key):
    private_key, _ = ec_key_pair
    payload = _auth_payload()
    payload.pop("sub")
    token = jwt.encode(payload, private_key, algorithm="ES256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_getter.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_invalid_uuid(db_session: AsyncSession, ec_key_pair, mock_signing_key):
    private_key, _ = ec_key_pair
    payload = _auth_payload(sub="not-a-uuid")
    token = jwt.encode(payload, private_key, algorithm="ES256")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
        mock_client_getter.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid user ID in token"


@pytest.mark.asyncio
async def test_get_current_user_jwk_client_error(db_session: AsyncSession):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.jwt.token")

    with patch("app.modules.auth.dependencies._get_jwk_client") as mock_client_getter:
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.side_effect = PyJWKClientError("Key not found")
        mock_client_getter.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db_session)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token"
