import os
import ssl


def _mode() -> str:
    return os.getenv("REDIS_SSL_CERT_REQS", "required").lower()  # required | optional | none


def _ca_certs_path() -> str | None:
    ca_path = os.getenv("REDIS_SSL_CA_CERTS")
    if not ca_path:
        return None
    if os.path.exists(ca_path):
        return ca_path
    # Check relative to backend directory or project root
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidate = os.path.join(base_dir, ca_path.lstrip("./"))
    if os.path.exists(candidate):
        return candidate
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
