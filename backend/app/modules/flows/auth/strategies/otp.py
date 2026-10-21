import asyncio
import logging
import re
import time
from typing import Any
import pyotp

from app.engine.browser.session import BrowserSession
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.flows.auth.verifier import AuthReasonCode, verify_authenticated
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class OTPStrategy:
    """Authenticates via One-Time-Password (TOTP) or email OTP codes (§Prompt B)."""

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

        page = browser.page
        if not page:
            return AuthResult(
                success=False,
                failure_reason="Browser page is not initialized",
                reason_code=AuthReasonCode.UNKNOWN,
                failure_category="AUTH",
            )

        try:
            # 1. Navigate if not already on the auth page
            if not page.url or page.url.endswith("/"):
                await browser.navigate(login_url)

            # 2. Derive OTP code: require TOTP secret (pyotp) or email OTP. NO 123456 fallback.
            totp_secret = (
                getattr(credential, "totp_secret", None)
                or getattr(credential, "otp_secret", None)
            )
            otp_code: str | None = None

            if totp_secret:
                try:
                    otp_code = pyotp.TOTP(totp_secret).now()
                except Exception as e:
                    logger.warning("Failed to compute TOTP from secret: %s", e)

            # If no TOTP secret, attempt temp-mail inbox lookup if email is available
            if not otp_code and getattr(credential, "email", None):
                email = credential.email
                try:
                    from app.engine.email.provider import get_temp_email_provider
                    temp_mail = get_temp_email_provider()
                    if temp_mail and hasattr(credential, "mailbox_handle"):
                        msg = await temp_mail.wait_for_message(credential.mailbox_handle, timeout_seconds=10.0)
                        if msg:
                            # Search for 6-digit number in subject or body
                            match = re.search(r"\b\d{6}\b", msg.body_text or msg.subject)
                            if match:
                                otp_code = match.group(0)
                    else:
                        # Check local fixture temp inbox if running in local test environment
                        inbox_res = await page.request.get(f"/api/inbox/{email}")
                        if inbox_res.ok:
                            inbox_data = await inbox_res.json()
                            otp_code = inbox_data.get("latest_code")
                except Exception as mail_err:
                    logger.debug("Temp-mail OTP retrieval attempt failed: %s", mail_err)

            # Check if explicit code provided directly in credential
            if not otp_code and hasattr(credential, "otp_code"):
                otp_code = str(credential.otp_code)

            if not otp_code:
                # Invariant 3: No simulated success. Fail-closed without 123456 fallback.
                return AuthResult(
                    success=False,
                    failure_reason="OTP verification requires a TOTP secret or active email mailbox; no code available",
                    reason_code=AuthReasonCode.NEEDS_OTP,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=False, error="Missing OTP code", duration_ms=int((time.monotonic() - t0) * 1000))],
                )

            # 3. Locate OTP field dynamically by label, autocomplete=one-time-code, inputmode and length
            otp_locator = None

            # a) autocomplete=one-time-code
            ac_el = page.locator("input[autocomplete='one-time-code']")
            if await ac_el.count() > 0 and await ac_el.first.is_visible():
                otp_locator = ac_el.first

            # b) inputmode=numeric with length 6-8
            if not otp_locator:
                num_el = page.locator("input[inputmode='numeric']")
                if await num_el.count() > 0 and await num_el.first.is_visible():
                    otp_locator = num_el.first

            # c) accessible label matching OTP / verification code
            if not otp_locator:
                for label_pat in (r"one-time", r"verification", r"authenticator", r"code", r"otp"):
                    lbl_el = page.get_by_label(re.compile(label_pat, re.I))
                    if await lbl_el.count() > 0 and await lbl_el.first.is_visible():
                        otp_locator = lbl_el.first
                        break

            # d) heuristic attribute selector fallback
            if not otp_locator:
                for sel in ("input[name*='otp']", "input[name*='code']", "input[id*='otp']", "input[id*='code']"):
                    el = page.locator(sel)
                    if await el.count() > 0 and await el.first.is_visible():
                        otp_locator = el.first
                        break

            if not otp_locator:
                # Escalate to agent loop with screenshot if deterministic selectors cannot find field
                if event_recorder:
                    try:
                        ss_bytes = await page.screenshot()
                        event_recorder("auth_escalation_to_agent", {
                            "strategy": "otp",
                            "reason": "Could not locate OTP input field",
                            "url": page.url,
                            "screenshot_size": len(ss_bytes),
                        })
                    except Exception:
                        pass

                return AuthResult(
                    success=False,
                    failure_reason="Could not locate OTP input field on page",
                    reason_code=AuthReasonCode.NEEDS_OTP,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=False, error="OTP field not found", duration_ms=int((time.monotonic() - t0) * 1000))],
                )

            # 4. Fill OTP and submit
            await otp_locator.fill(otp_code)

            submit_btn = None
            for btn_sel in (
                "button[type=submit]",
                "input[type=submit]",
                "button:has-text('Verify')",
                "button:has-text('Submit')",
                "button:has-text('Continue')",
                "button:has-text('Log In')",
            ):
                btn = page.locator(btn_sel)
                if await btn.count() > 0 and await btn.first.is_visible():
                    submit_btn = btn.first
                    break

            if submit_btn:
                await submit_btn.click()
            else:
                await otp_locator.press("Enter")

            # 5. Wait for the result of the submit (navigation / DOM mutation)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=4000)
            except Exception:
                pass
            await asyncio.sleep(0.5)

            # 6. Verify authentication through unified verify_authenticated
            is_authed, reason_code = await verify_authenticated(browser, capability)

            if is_authed:
                session_state = await browser.save_session_state()
                return AuthResult(
                    success=True,
                    session_state=session_state,
                    reason_code=AuthReasonCode.SUCCESS,
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=True, reason_code=AuthReasonCode.SUCCESS, duration_ms=int((time.monotonic() - t0) * 1000))],
                )
            else:
                return AuthResult(
                    success=False,
                    failure_reason=f"OTP verification failed with reason: {reason_code}",
                    reason_code=reason_code,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=False, error=reason_code, reason_code=reason_code, duration_ms=int((time.monotonic() - t0) * 1000))],
                )

        except Exception as e:
            logger.error("OTP strategy exception: %s", e)
            return AuthResult(
                success=False,
                failure_reason=str(e),
                reason_code=AuthReasonCode.UNKNOWN,
                failure_category="AUTH",
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="otp", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000))],
            )
