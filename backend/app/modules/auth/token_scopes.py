from __future__ import annotations

import logging
from typing import Callable, Iterable

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

# Standard scopes
SCOPE_ALL = "*"
SCOPE_FLOWS_READ = "flows:read"
SCOPE_FLOWS_WRITE = "flows:write"
SCOPE_EXECUTIONS_READ = "executions:read"
SCOPE_EXECUTIONS_WRITE = "executions:write"
SCOPE_CI_VALIDATE = "ci:validate"
SCOPE_INTEGRATIONS_MANAGE = "integrations:manage"
SCOPE_ORG_MANAGE = "org:manage"

ALL_SCOPES = {
    SCOPE_ALL,
    SCOPE_FLOWS_READ,
    SCOPE_FLOWS_WRITE,
    SCOPE_EXECUTIONS_READ,
    SCOPE_EXECUTIONS_WRITE,
    SCOPE_CI_VALIDATE,
    SCOPE_INTEGRATIONS_MANAGE,
    SCOPE_ORG_MANAGE,
}


def has_scope(granted_scopes: Iterable[str] | None, required_scope: str) -> bool:
    """Check if granted scopes satisfy the required scope."""
    if not granted_scopes:
        return False
    granted_set = set(granted_scopes)
    if SCOPE_ALL in granted_set:
        return True
    if required_scope in granted_set:
        return True

    # Check prefix wildcard, e.g. 'flows:*' satisfies 'flows:read'
    if ":" in required_scope:
        domain = required_scope.split(":", 1)[0]
        if f"{domain}:*" in granted_set:
            return True

    return False


def require_scope(required_scope: str) -> Callable:
    """FastAPI dependency to enforce API token scope on endpoints."""
    from app.modules.auth.dependencies import get_current_user
    from app.modules.users.models import User

    async def _scope_checker(
        user: User = Depends(get_current_user),
    ) -> User:
        user_scopes = getattr(user, "_token_scopes", [SCOPE_ALL])
        if not has_scope(user_scopes, required_scope):
            logger.warning(
                "User %s attempted action requiring '%s' with token scopes %s",
                user.id,
                required_scope,
                user_scopes,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Token missing required scope '{required_scope}'",
            )
        return user

    return _scope_checker
