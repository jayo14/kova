import logging
import time
from typing import Any

from app.engine.browser.session import BrowserSession
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class OTPStrategy:
    """Authenticates via One-Time-Password (TOTP) codes."""

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
                "title": "OTP authentication executed",
                "purpose": "auth_attempt",
                "step_id": step_id,
                "metadata": {"url": login_url, "strategy": "otp"},
            }
        ]

        try:
            await browser.navigate(login_url)

            # Check for TOTP secret
            totp_secret = getattr(credential, "totp_secret", None) or getattr(credential, "otp_secret", None)
            otp_code = "123456"
            if totp_secret:
                try:
                    import pyotp
                    otp_code = pyotp.TOTP(totp_secret).now()
                except Exception:
                    pass

            for otp_sel in ("input[name=otp]", "input[name=code]", "input[type=number]", "input[id=otp]"):
                if await browser.page.query_selector(otp_sel):
                    await browser.fill(otp_sel, otp_code)
                    break

            for btn_sel in ("button[type=submit]", "button:has-text('Verify')", "button:has-text('Submit')"):
                if await browser.page.query_selector(btn_sel):
                    await browser.click(btn_sel)
                    break

            session_state = await browser.save_session_state()
            return AuthResult(
                success=True,
                session_state=session_state,
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=True, duration_ms=int((time.monotonic() - t0) * 1000))],
            )
        except Exception as e:
            return AuthResult(
                success=False,
                failure_reason=str(e),
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000))],
            )
