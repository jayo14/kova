import logging
import os
import ssl

logger = logging.getLogger(__name__)

try:
    from dotenv import find_dotenv, load_dotenv

    for env_path in (".env", "backend/.env", "../backend/.env"):
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
    else:
        found = find_dotenv(usecwd=True)
        if found:
            load_dotenv(found)
except Exception:
    pass


def _mode() -> str:
    return os.getenv("REDIS_SSL_CERT_REQS", "required").lower()  # required | optional | none


def _ca_certs_path() -> str | None:
    ca_path = os.getenv("REDIS_SSL_CA_CERTS")
    if not ca_path:
        return None
    if os.path.exists(ca_path):
        return ca_path
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidate = os.path.join(base_dir, ca_path.lstrip("./"))
    if os.path.exists(candidate):
        return candidate
    repo_root = os.path.dirname(base_dir)
    root_candidate = os.path.join(repo_root, ca_path.lstrip("./"))
    if os.path.exists(root_candidate):
        return root_candidate
    return ca_path


def redispy_ssl_kwargs() -> dict:
    """redis-py clients (redis.asyncio): STRINGS, not ssl.CERT_* constants."""
    kw = {"ssl_cert_reqs": _mode()}
    ca = _ca_certs_path()
    if ca:
        kw["ssl_ca_certs"] = ca
    return kw


def celery_ssl_options() -> dict:
    """Celery broker_use_ssl / redis_backend_use_ssl: ssl.CERT_* constants."""
    m = {"required": ssl.CERT_REQUIRED, "optional": ssl.CERT_OPTIONAL, "none": ssl.CERT_NONE}
    opts = {"ssl_cert_reqs": m.get(_mode(), ssl.CERT_REQUIRED)}
    ca = _ca_certs_path()
    if ca:
        opts["ssl_ca_certs"] = ca
    return opts


def verify_redis_tls_connectivity(url: str | None = None) -> bool:
    """Startup self-test that connects to Redis, PINGs, and logs the TLS mode.

    Logs a loud security warning if mode is 'none'.
    """
    mode = _mode()
    if mode == "none":
        logger.warning(
            "⚠️  SECURITY WARNING: REDIS_SSL_CERT_REQS is set to 'none'! "
            "TLS encryption is active, but certificate verification is DISABLED. "
            "Connections are vulnerable to man-in-the-middle attacks. "
            "Provide REDIS_SSL_CA_CERTS and set REDIS_SSL_CERT_REQS=required for production."
        )
    else:
        logger.info("Redis TLS verification mode configured: %s", mode)

    test_url = url or os.getenv("REDIS_URL")
    if not test_url:
        return True

    try:
        import redis

        kwargs: dict = {}
        if "rediss://" in test_url:
            kwargs = redispy_ssl_kwargs()
        client = redis.from_url(test_url, socket_connect_timeout=3.0, socket_timeout=3.0, **kwargs)
        client.ping()
        client.close()
        logger.info("Redis TLS startup self-test PING succeeded (mode=%s)", mode)
        return True
    except Exception as exc:
        logger.error("Redis TLS startup self-test failed (mode=%s): %s", mode, exc)
        return False
