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
    reason_code: str | None = None


@dataclass
class AuthResult:
    success: bool
    session_state: SessionState | None = None
    failure_reason: str | None = None
    reason_code: str | None = None
    failure_category: str | None = None  # Always "AUTH" on failure (§Prompt B)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[AuthAttempt] = field(default_factory=list)

    def __post_init__(self):
        if not self.success and not self.failure_category:
            self.failure_category = "AUTH"


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
