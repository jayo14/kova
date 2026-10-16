"""GitHub Webhook signature verification and payload normalization."""
from __future__ import annotations

import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_github_signature(payload_bytes: bytes, secret: str, signature_header: str | None) -> bool:
    """Verify GitHub webhook payload HMAC-SHA256 signature using constant-time comparison."""
    if not signature_header or not secret:
        return False
    if not signature_header.startswith("sha256="):
        return False

    expected_sig = signature_header[7:].strip()
    mac = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256)
    computed_sig = mac.hexdigest()
    return hmac.compare_digest(computed_sig, expected_sig)
