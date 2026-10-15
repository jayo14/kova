import logging
import time
from typing import Any

from app.engine.browser.session import BrowserSession
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class MagicLinkStrategy:
    """Authenticates via magic-link email delivery."""

    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        login_url = capability.login_url or "/login"
        email = getattr(credential, "email", "")
        t0 = time.monotonic()
        step_id = f"auth:{capability.name}:attempt_1"

        evidence: list[dict[str, Any]] = [
            {
                "type": "network_log",
                "title": "Magic link request sent",
                "purpose": "auth_attempt",
                "step_id": step_id,
                "metadata": {"url": login_url, "email": email, "strategy": "magic_link"},
            }
        ]

        try:
            await browser.navigate(login_url)
            # Try to locate email input and magic link trigger
            for sel in ("input[type=email]", "input[name=email]"):
                if await browser.page.query_selector(sel):
                    await browser.fill(sel, email)
                    break

            for btn_sel in ("button:has-text('Send Link')", "button:has-text('Magic Link')", "button[type=submit]"):
                if await browser.page.query_selector(btn_sel):
                    await browser.click(btn_sel)
                    break

            # Magic link requires human takeover or IMAP retrieval
            if event_recorder:
                event_recorder(
                    "agent_question",
                    {
                        "type": "magic_link_requested",
                        "email": email,
                        "question": "A magic login link was requested. Please paste the magic link URL to continue.",
                    },
                )

            return AuthResult(
                success=False,
                failure_reason="Magic link sent; waiting for email link retrieval or human takeover",
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=False, error="Awaiting magic link", duration_ms=int((time.monotonic() - t0) * 1000))],
            )
        except Exception as e:
            return AuthResult(
                success=False,
                failure_reason=str(e),
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000))],
            )
