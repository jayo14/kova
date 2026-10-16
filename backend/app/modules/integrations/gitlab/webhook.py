"""GitLab Webhook token verification and payload normalization."""
from __future__ import annotations

import secrets
import logging

logger = logging.getLogger(__name__)


def verify_gitlab_token(token_header: str | None, secret: str) -> bool:
    """Verify GitLab webhook X-Gitlab-Token using constant-time string comparison."""
    if not token_header or not secret:
        return False
    return secrets.compare_digest(token_header.strip(), secret.strip())
