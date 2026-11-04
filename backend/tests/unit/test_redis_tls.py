import os
import ssl
from unittest import mock

import pytest

from app.core.redis_tls import (
    _mode,
    celery_ssl_options,
    redispy_ssl_kwargs,
    verify_redis_tls_connectivity,
)


def test_mode_default():
    with mock.patch.dict(os.environ, {}, clear=True):
        assert _mode() == "required"


@pytest.mark.parametrize("env_val,expected", [
    ("none", "none"),
    ("NONE", "none"),
    ("optional", "optional"),
    ("OPTIONAL", "optional"),
    ("required", "required"),
    ("REQUIRED", "required"),
])
def test_mode_values(env_val, expected):
    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": env_val}):
        assert _mode() == expected


def test_redispy_ssl_kwargs_without_ca():
    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "none"}, clear=True):
        kw = redispy_ssl_kwargs()
        assert kw == {"ssl_cert_reqs": "none"}
        assert isinstance(kw["ssl_cert_reqs"], str)


def test_redispy_ssl_kwargs_with_ca(tmp_path):
    ca_file = tmp_path / "test-ca.crt"
    ca_file.write_text("CERT")
    with mock.patch.dict(os.environ, {
        "REDIS_SSL_CERT_REQS": "required",
        "REDIS_SSL_CA_CERTS": str(ca_file),
    }):
        kw = redispy_ssl_kwargs()
        assert kw["ssl_cert_reqs"] == "required"
        assert kw["ssl_ca_certs"] == str(ca_file)


def test_celery_ssl_options_without_ca():
    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "none"}, clear=True):
        opts = celery_ssl_options()
        assert opts == {"ssl_cert_reqs": ssl.CERT_NONE}

    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "optional"}, clear=True):
        opts = celery_ssl_options()
        assert opts == {"ssl_cert_reqs": ssl.CERT_OPTIONAL}

    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "required"}, clear=True):
        opts = celery_ssl_options()
        assert opts == {"ssl_cert_reqs": ssl.CERT_REQUIRED}


def test_celery_ssl_options_with_ca(tmp_path):
    ca_file = tmp_path / "test-ca.crt"
    ca_file.write_text("CERT")
    with mock.patch.dict(os.environ, {
        "REDIS_SSL_CERT_REQS": "required",
        "REDIS_SSL_CA_CERTS": str(ca_file),
    }):
        opts = celery_ssl_options()
        assert opts["ssl_cert_reqs"] == ssl.CERT_REQUIRED
        assert opts["ssl_ca_certs"] == str(ca_file)


def test_verify_redis_tls_connectivity_mode_none(caplog):
    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "none", "REDIS_URL": ""}):
        with caplog.at_level("WARNING"):
            result = verify_redis_tls_connectivity()
            assert result is True
            assert "SECURITY WARNING" in caplog.text


def test_verify_redis_tls_connectivity_ping_success():
    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "required", "REDIS_URL": "redis://localhost:6379/0"}):
        with mock.patch("redis.from_url") as mock_from_url:
            mock_client = mock.MagicMock()
            mock_client.ping.return_value = True
            mock_from_url.return_value = mock_client
            assert verify_redis_tls_connectivity() is True
            mock_client.ping.assert_called_once()
            mock_client.close.assert_called_once()


def test_verify_redis_tls_connectivity_ping_failure():
    with mock.patch.dict(os.environ, {"REDIS_SSL_CERT_REQS": "required", "REDIS_URL": "rediss://localhost:6379/0"}):
        with mock.patch("redis.from_url") as mock_from_url:
            mock_from_url.side_effect = Exception("SSL handshake failed")
            assert verify_redis_tls_connectivity() is False
