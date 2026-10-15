import asyncio
import ipaddress
import logging
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

from app.engine.browser.auth import classify_auth_page, find_submit_button
from app.engine.browser.session import BrowserSession
from app.modules.credentials.crypto import decrypt_credential
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_safe_url(url: str, allow_local: bool = True) -> bool:
    """Validate target URL against malicious redirection and SSRF."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False

        if allow_local and hostname in ("localhost", "127.0.0.1", "::1"):
            return True

        if hostname == "metadata.google.internal" or hostname == "169.254.169.254":
            return False

        try:
            ip = ipaddress.ip_address(hostname)
            if not allow_local and any(ip in net for net in _PRIVATE_NETWORKS):
                return False
        except ValueError:
            pass

        return True
    except Exception:
        return False


class PasswordFormStrategy:
    """Authenticates against standard email and password forms."""

    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        login_url = capability.login_url or "/login"
        success_pattern = capability.success_url_pattern or r"/(dashboard|app|courses|profile|home)"
        attempts: list[AuthAttempt] = []
        evidence_list: list[dict[str, Any]] = []

        # Decrypt credential
        raw_pwd = getattr(credential, "password", "")
        if hasattr(credential, "get_password"):
            password = credential.get_password()
        else:
            try:
                password = decrypt_credential(raw_pwd)
            except Exception:
                password = raw_pwd

        email = getattr(credential, "email", "")

        for attempt_num in (1, 2):
            t0 = time.monotonic()
            step_id = f"auth:{capability.name}:attempt_{attempt_num}"

            # SSRF check on login url
            if login_url.startswith("http") and not _is_safe_url(login_url):
                return AuthResult(
                    success=False,
                    failure_reason=f"SSRF violation: Login URL '{login_url}' is not allowed",
                    evidence=evidence_list,
                    attempts=[AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error="SSRF blocked")],
                )

            try:
                # 1. Navigate
                await browser.navigate(login_url)
                try:
                    if browser.page:
                        await browser.page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

                # Check if already authenticated
                current_url = browser.page.url if browser.page else ""
                if re.search(success_pattern, current_url):
                    session_state = await browser.save_session_state()
                    attempts.append(AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=True, duration_ms=int((time.monotonic() - t0) * 1000)))
                    return AuthResult(
                        success=True,
                        session_state=session_state,
                        evidence=evidence_list,
                        attempts=attempts,
                    )

                # 2. Locate inputs
                email_selector = await self._find_input(browser, ["input[type=email]", "input[name=email]", "input[id=email]", "input[autocomplete=email]", "input[type=text]"])
                pwd_selector = await self._find_input(browser, ["input[type=password]", "input[name=password]", "input[id=password]"])

                if not pwd_selector:
                    # Classify page
                    if browser.page:
                        classification = await classify_auth_page(browser.page, current_url)
                        if classification.kind != "login":
                            reason = f"Expected login page, got {classification.kind}"
                            attempts.append(AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error=reason))
                            return AuthResult(success=False, failure_reason=reason, evidence=evidence_list, attempts=attempts)

                    reason = "No password input visible on login page"
                    attempts.append(AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error=reason))
                    if attempt_num == 2:
                        return AuthResult(success=False, failure_reason=reason, evidence=evidence_list, attempts=attempts)
                    continue

                submit_btn = await find_submit_button(browser.page) if browser.page else "button[type=submit]"
                if not submit_btn:
                    submit_btn = "button[type=submit], input[type=submit], button:has-text('Sign In'), button:has-text('Log In')"

                # 3. Capture pre-submit screenshot evidence
                pre_ss = await self._capture_screenshot_evidence(browser, step_id, "pre_submit")
                if pre_ss:
                    evidence_list.append(pre_ss)

                # 4. Input credentials
                if email_selector:
                    await browser.fill(email_selector, email)
                await browser.fill(pwd_selector, password)

                # 5. Capture network log / submit record evidence (redacting passwords & cookies!)
                evidence_list.append({
                    "type": "network_log",
                    "title": f"Auth submission network log ({attempt_num})",
                    "purpose": "auth_attempt",
                    "step_id": step_id,
                    "metadata": {
                        "url": current_url,
                        "email": email,
                        "action": "submit",
                        "password_redacted": True,
                    },
                })

                # 6. Click submit
                try:
                    await browser.click(submit_btn)
                except Exception:
                    await browser.page.keyboard.press("Enter")

                # Wait for navigation / response
                try:
                    if browser.page:
                        await browser.page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass
                await asyncio.sleep(0.5)

                # 7. Capture post-submit screenshot evidence
                post_ss = await self._capture_screenshot_evidence(browser, step_id, "post_submit")
                if post_ss:
                    evidence_list.append(post_ss)

                # 8. Check outcome
                new_url = browser.page.url if browser.page else ""
                auth_succeeded = bool(re.search(success_pattern, new_url) or new_url != current_url and not re.search(r"/(login|signin)", new_url))

                if auth_succeeded:
                    session_state = await browser.save_session_state()
                    attempts.append(AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=True, duration_ms=int((time.monotonic() - t0) * 1000)))
                    return AuthResult(
                        success=True,
                        session_state=session_state,
                        evidence=evidence_list,
                        attempts=attempts,
                    )
                else:
                    error_msg = f"Post-login URL '{new_url}' did not match success pattern '{success_pattern}'"
                    attempts.append(AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error=error_msg, duration_ms=int((time.monotonic() - t0) * 1000)))
                    if attempt_num == 1:
                        await asyncio.sleep(1.0)
                        continue
                    return AuthResult(
                        success=False,
                        failure_reason=error_msg,
                        evidence=evidence_list,
                        attempts=attempts,
                    )

            except Exception as e:
                logger.warning("Auth attempt %d failed: %s", attempt_num, e)
                attempts.append(AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000)))
                if attempt_num == 2:
                    return AuthResult(
                        success=False,
                        failure_reason=f"Authentication exception: {e}",
                        evidence=evidence_list,
                        attempts=attempts,
                    )

        return AuthResult(
            success=False,
            failure_reason="Authentication failed after 2 attempts",
            evidence=evidence_list,
            attempts=attempts,
        )

    async def _find_input(self, browser: BrowserSession, selectors: list[str]) -> str | None:
        if not browser.page:
            return None
        for sel in selectors:
            try:
                el = await browser.page.query_selector(sel)
                if el and await el.is_visible():
                    return sel
            except Exception:
                continue
        return None

    async def _capture_screenshot_evidence(
        self, browser: BrowserSession, step_id: str, phase: str
    ) -> dict[str, Any] | None:
        try:
            png_bytes = await browser.screenshot()
            return {
                "type": "screenshot",
                "title": f"Auth {phase} screenshot",
                "purpose": "auth_attempt",
                "step_id": step_id,
                "metadata": {
                    "phase": phase,
                    "url": browser.page.url if browser.page else "",
                    "size_bytes": len(png_bytes) if png_bytes else 0,
                },
            }
        except Exception:
            return None
