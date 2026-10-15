from dataclasses import dataclass, field
from typing import Any, Protocol

from app.engine.browser.session import BrowserSession, SessionState
from app.modules.product_graph.schemas import AuthCapability


@dataclass
class AuthAttempt:
    attempt_number: int
    strategy: str
    success: bool
    error: str | None = None
    duration_ms: int = 0


@dataclass
class AuthResult:
    success: bool
    session_state: SessionState | None = None
    failure_reason: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[AuthAttempt] = field(default_factory=list)


class AuthStrategy(Protocol):
    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        ...
