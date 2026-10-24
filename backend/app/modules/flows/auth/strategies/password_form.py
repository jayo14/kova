import asyncio
import ipaddress
import logging
import re
import socket
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from app.engine.browser.auth import classify_auth_page, find_submit_button
from app.engine.browser.session import BrowserSession
from app.modules.credentials.crypto import decrypt_credential
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.flows.auth.verifier import AuthReasonCode, verify_authenticated
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
    """Authenticates against standard email and password forms (§Prompt B)."""

    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        login_url = capability.login_url or "/login"
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

        email = getattr(credential, "email", "") or getattr(credential, "username", "")

        for attempt_num in (1, 2):
            t0 = time.monotonic()
            step_id = f"auth:{capability.name}:attempt_{attempt_num}"

            # SSRF check on login url
            if login_url.startswith("http") and not _is_safe_url(login_url):
                return AuthResult(
                    success=False,
                    failure_reason=f"SSRF violation: Login URL '{login_url}' is not allowed",
                    reason_code=AuthReasonCode.SITE_ERROR,
                    failure_category="AUTH",
                    evidence=evidence_list,
                    attempts=[AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error="SSRF blocked", reason_code=AuthReasonCode.SITE_ERROR)],
                )

            try:
                # 1. Navigate if needed
                current_url = browser.page.url if browser.page else ""
                if login_url.startswith("http"):
                    if not current_url or current_url != login_url:
                        await browser.navigate(login_url)
                elif login_url and current_url:
                    target_abs = urljoin(current_url, login_url)
                    if current_url != target_abs and not (login_url == "/" and current_url.rstrip("/").count("/") <= 2):
                        await browser.navigate(target_abs)

                page = browser.page
                if not page:
                    return AuthResult(
                        success=False,
                        failure_reason="Browser page is not initialized",
                        reason_code=AuthReasonCode.UNKNOWN,
                        failure_category="AUTH",
                    )

                # Check if already authenticated before performing action
                is_authed, pre_reason = await verify_authenticated(browser, capability)
                if is_authed:
                    session_state = await browser.save_session_state()
                    return AuthResult(
                        success=True,
                        session_state=session_state,
                        reason_code=AuthReasonCode.SUCCESS,
                        evidence=evidence_list,
                        attempts=[AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=True, reason_code=AuthReasonCode.SUCCESS, duration_ms=int((time.monotonic() - t0) * 1000))],
                    )

                # 2. Check for modal trigger if form is not initially visible
                pwd_sel = await self._find_input(browser, ["input[type=password]", "input[name*='pass']"])
                if not pwd_sel:
                    # Look for sign in modal buttons
                    for modal_btn in ("button:has-text('Sign In')", "button:has-text('Log In')", "#openModalBtn", "[data-auth-modal]"):
                        mb = page.locator(modal_btn)
                        if await mb.count() > 0 and await mb.first.is_visible():
                            await mb.first.click()
                            await asyncio.sleep(0.3)
                            break

                # 3. Locate inputs deterministically
                user_sel = await self._find_input(
                    browser,
                    [
                        "input[type=email]",
                        "input[name=email]",
                        "input[id=email]",
                        "input[name=username]",
                        "input[id=username]",
                        "input[name=identifier]",
                        "input[id=identifier]",
                        "input[autocomplete=username]",
                        "input[autocomplete=email]",
                    ],
                )
                pwd_sel = await self._find_input(
                    browser,
                    [
                        "input[type=password]",
                        "input[name=password]",
                        "input[id=password]",
                        "input[autocomplete=current-password]",
                    ],
                )

                target_frame = None
                frames = getattr(page, "frames", None)
                if (not user_sel or not pwd_sel) and isinstance(frames, (list, tuple)):
                    for frame in frames:
                        if frame == page.main_frame:
                            continue
                        f_user = await self._find_input_in_frame(
                            frame,
                            [
                                "input[type=email]",
                                "input[name=email]",
                                "input[id=email]",
                                "input[name=username]",
                                "input[id=username]",
                                "input[name=identifier]",
                                "input[id=identifier]",
                                "input[autocomplete=username]",
                                "input[autocomplete=email]",
                            ],
                        )
                        f_pwd = await self._find_input_in_frame(
                            frame,
                            [
                                "input[type=password]",
                                "input[name=password]",
                                "input[id=password]",
                                "input[autocomplete=current-password]",
                            ],
                        )
                        if f_user and f_pwd:
                            target_frame = frame
                            user_sel = f_user
                            pwd_sel = f_pwd
                            break

                # If multi-step login, user input might appear first before password
                if user_sel and not pwd_sel:
                    await browser.fill(user_sel, email)
                    next_btn = page.locator("button:has-text('Next'), button:has-text('Continue'), #nextBtn")
                    if await next_btn.count() > 0 and await next_btn.first.is_visible():
                        await next_btn.first.click()
                        await asyncio.sleep(0.3)
                        pwd_sel = await self._find_input(browser, ["input[type=password]", "input[name=password]", "input[id=password]"])

                # Escalate to agent loop with screenshot if fields cannot be located
                if not user_sel or not pwd_sel:
                    screenshot = await self._capture_screenshot_evidence(browser, step_id, "form_unlocatable")
                    if screenshot:
                        evidence_list.append(screenshot)

                    if event_recorder:
                        event_recorder("auth_escalation_to_agent", {
                            "strategy": "password_form",
                            "reason": "Deterministic selectors could not locate login fields",
                            "user_found": bool(user_sel),
                            "password_found": bool(pwd_sel),
                            "url": page.url,
                        })

                    return AuthResult(
                        success=False,
                        failure_reason="Could not locate email/username and password fields on login page",
                        reason_code=AuthReasonCode.UNKNOWN,
                        failure_category="AUTH",
                        evidence=evidence_list,
                        attempts=[AuthAttempt(attempt_number=attempt_num, strategy="password_form", success=False, error="Fields not found", reason_code=AuthReasonCode.UNKNOWN, duration_ms=int((time.monotonic() - t0) * 1000))],
                    )

                # Capture pre-submit screenshot and network log evidence
                pre_ss = await self._capture_screenshot_evidence(browser, step_id, "pre_submit")
                if pre_ss:
                    evidence_list.append(pre_ss)

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

                # 4. Fill credentials & 5. Submit
                if target_frame:
                    await target_frame.fill(user_sel, email)
                    await target_frame.fill(pwd_sel, password)
                    submit_btn = await target_frame.query_selector(
                        "button[type=submit], input[type=submit], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Authorize'), button"
                    )
                    if submit_btn and await submit_btn.is_visible():
                        await submit_btn.click()
                    else:
                        await target_frame.locator(pwd_sel).press("Enter")
                else:
                    await browser.fill(user_sel, email)
                    await browser.fill(pwd_sel, password)

                    submit_btn = await find_submit_button(browser.page)
                    if submit_btn:
                        try:
                            await browser.click(submit_btn)
                        except Exception:
                            await page.keyboard.press("Enter")
                    else:
                        await page.keyboard.press("Enter")

                # Wait for response / navigation
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass
                await asyncio.sleep(0.5)

                # 6. Capture post-submit screenshot evidence
                post_ss = await self._capture_screenshot_evidence(browser, step_id, "post_submit")
                if post_ss:
                    evidence_list.append(post_ss)

                # 7. Check outcome via unified verify_authenticated
                success_pattern = getattr(capability, "success_url_pattern", None)
                new_url = browser.page.url if browser.page else ""

                is_authed, reason_code = await verify_authenticated(browser, capability)
                if not is_authed and success_pattern and success_pattern not in ("/", "^/$", ".*"):
                    if re.search(success_pattern, new_url):
                        is_authed = True
                        reason_code = AuthReasonCode.SUCCESS
                elif is_authed and success_pattern and success_pattern not in ("/", "^/$", ".*"):
                    if not re.search(success_pattern, new_url):
                        is_authed = False
                        reason_code = AuthReasonCode.UNKNOWN

                if is_authed:
                    session_state = await browser.save_session_state()
                    attempts.append(AuthAttempt(
                        attempt_number=attempt_num,
                        strategy="password_form",
                        success=True,
                        reason_code=AuthReasonCode.SUCCESS,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    ))
                    return AuthResult(
                        success=True,
                        session_state=session_state,
                        reason_code=AuthReasonCode.SUCCESS,
                        evidence=evidence_list,
                        attempts=attempts,
                    )
                else:
                    error_msg = (
                        f"Post-login URL '{new_url}' did not match success pattern '{success_pattern}'"
                        if (success_pattern and not re.search(success_pattern, new_url))
                        else f"Password authentication failed: {reason_code}"
                    )
                    # Record attempt failure with specific reason code
                    attempts.append(AuthAttempt(
                        attempt_number=attempt_num,
                        strategy="password_form",
                        success=False,
                        error=error_msg,
                        reason_code=reason_code,
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    ))

                    # If 2FA OTP is required and credential contains OTP secret, complete second factor via OTPStrategy
                    if reason_code == AuthReasonCode.NEEDS_OTP and (
                        getattr(credential, "totp_secret", None)
                        or getattr(credential, "otp_secret", None)
                        or hasattr(credential, "otp_code")
                    ):
                        from app.modules.flows.auth.strategies.otp import OTPStrategy
                        return await OTPStrategy().execute(
                            capability=capability,
                            browser=browser,
                            credential=credential,
                            execution_id=execution_id,
                            event_recorder=event_recorder,
                        )

                    # If OTP or CAPTCHA is required, do not retry password
                    if reason_code in (AuthReasonCode.NEEDS_OTP, AuthReasonCode.NEEDS_CAPTCHA, AuthReasonCode.SSO_ONLY):
                        return AuthResult(
                            success=False,
                            failure_reason=f"Authentication blocked: {reason_code}",
                            reason_code=reason_code,
                            failure_category="AUTH",
                            evidence=evidence_list,
                            attempts=attempts,
                        )

                    if attempt_num == 1:
                        await asyncio.sleep(0.5)
                        continue

                    return AuthResult(
                        success=False,
                        failure_reason=error_msg,
                        reason_code=reason_code,
                        failure_category="AUTH",
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
                        reason_code=AuthReasonCode.UNKNOWN,
                        failure_category="AUTH",
                        evidence=evidence_list,
                        attempts=attempts,
                    )

        return AuthResult(
            success=False,
            failure_reason="Authentication failed after attempts",
            reason_code=AuthReasonCode.BAD_CREDENTIALS,
            failure_category="AUTH",
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

    async def _find_input_in_frame(self, frame: Any, selectors: list[str]) -> str | None:
        for sel in selectors:
            try:
                el = await frame.query_selector(sel)
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
