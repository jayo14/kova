import logging
import time
from typing import Any

from app.engine.browser.session import BrowserSession
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class OAuthStrategy:
    """Authenticates via third-party OAuth redirect requiring human takeover."""

    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        login_url = capability.login_url or "/login"
        t0 = time.monotonic()
        step_id = f"auth:{capability.name}:attempt_1"

        evidence: list[dict[str, Any]] = [
            {
                "type": "event_log",
                "title": "OAuth takeover requested",
                "purpose": "auth_attempt",
                "step_id": step_id,
                "metadata": {"url": login_url, "strategy": "oauth"},
            }
        ]

        try:
            await browser.navigate(login_url)

            # Request human takeover via agent_question event
            if event_recorder:
                event_recorder(
                    "agent_question",
                    {
                        "type": "oauth_takeover_requested",
                        "question": "OAuth authentication requires human assistance. Please complete the login in the browser view.",
                    },
                )

            return AuthResult(
                success=False,
                failure_reason="OAuth authentication requires human takeover; awaiting operator completion",
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="oauth", success=False, error="Awaiting human takeover", duration_ms=int((time.monotonic() - t0) * 1000))],
            )
        except Exception as e:
            return AuthResult(
                success=False,
                failure_reason=str(e),
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="oauth", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000))],
            )
