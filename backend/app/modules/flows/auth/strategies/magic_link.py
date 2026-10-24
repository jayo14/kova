import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.engine.browser.session import BrowserSession
from app.engine.email.provider import extract_links, get_temp_email_provider, validate_email_link
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.flows.auth.verifier import AuthReasonCode, verify_authenticated
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class MagicLinkStrategy:
    """Authenticates via magic-link email delivery (§Prompt B)."""

    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        login_url = capability.login_url or "/login"
        email = getattr(credential, "email", "") or "tester@kova.internal"
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

        page = browser.page
        if not page:
            return AuthResult(
                success=False,
                failure_reason="Browser page is not initialized",
                reason_code=AuthReasonCode.UNKNOWN,
                failure_category="AUTH",
            )

        try:
            # 1. Navigate to login URL if needed
            if not page.url or page.url.endswith("/"):
                await browser.navigate(login_url)

            # 2. Locate email input and magic link trigger
            email_input = page.locator("input[type=email], input[name=email], input[id=email], input[placeholder*='email' i]")
            if await email_input.count() > 0 and await email_input.first.is_visible():
                await email_input.first.fill(email)

            btn = page.locator(
                "button:has-text('Send Link'), button:has-text('Magic Link'), button:has-text('Sign In'), button[type=submit], input[type=submit]"
            )
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click()
            else:
                await page.keyboard.press("Enter")

            # Wait for request to register
            await asyncio.sleep(0.5)

            # 3. Poll temp-mail inbox for magic link
            magic_link: str | None = None
            temp_mail = get_temp_email_provider()

            # Poll via configured temp-mail provider
            if temp_mail:
                try:
                    from app.engine.email.provider import MailboxHandle
                    mailbox_handle = getattr(credential, "mailbox_handle", None) or (
                        MailboxHandle(mailbox_id=email, address=email) if email else None
                    )
                    if mailbox_handle:
                        msg = await temp_mail.wait_for_message(mailbox_handle, timeout_seconds=15.0)
                        if msg:
                            links = extract_links(msg.body_text)
                            if links:
                                magic_link = links[0]
                except Exception as mail_err:
                    logger.debug("Temp-mail provider polling failed: %s", mail_err)

            if not magic_link:
                # Notify operator if human intervention is enabled
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
                    failure_reason="Magic link request submitted but no link was received in temp-mail inbox within timeout",
                    reason_code=AuthReasonCode.NEEDS_EMAIL_VERIFICATION,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=False, error="Inbox timeout", reason_code=AuthReasonCode.NEEDS_EMAIL_VERIFICATION, duration_ms=int((time.monotonic() - t0) * 1000))],
                )

            # 4. Security check on magic link
            app_host = urlparse(login_url).netloc or urlparse(page.url).netloc
            if not validate_email_link(magic_link, app_host):
                return AuthResult(
                    success=False,
                    failure_reason=f"Magic link '{magic_link}' failed SSRF or host validation",
                    reason_code=AuthReasonCode.SITE_ERROR,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=False, error="SSRF blocked", reason_code=AuthReasonCode.SITE_ERROR, duration_ms=int((time.monotonic() - t0) * 1000))],
                )

            # 5. Open the magic link in the SAME browser context
            await browser.navigate(magic_link)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            await asyncio.sleep(0.5)

            # 6. Run verify_authenticated
            is_authed, reason_code = await verify_authenticated(browser, capability)

            if is_authed:
                session_state = await browser.save_session_state()
                return AuthResult(
                    success=True,
                    session_state=session_state,
                    reason_code=AuthReasonCode.SUCCESS,
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=True, reason_code=AuthReasonCode.SUCCESS, duration_ms=int((time.monotonic() - t0) * 1000))],
                )
            else:
                return AuthResult(
                    success=False,
                    failure_reason=f"Magic link opened but verification failed: {reason_code}",
                    reason_code=reason_code,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=False, error=reason_code, reason_code=reason_code, duration_ms=int((time.monotonic() - t0) * 1000))],
                )

        except Exception as e:
            return AuthResult(
                success=False,
                failure_reason=str(e),
                reason_code=AuthReasonCode.UNKNOWN,
                failure_category="AUTH",
                evidence=evidence,
                attempts=[AuthAttempt(attempt_number=1, strategy="magic_link", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000))],
            )
