"""Deterministic authentication verification and reason code classifier (§Prompt B).

Evaluates browser session state post-authentication attempt to tell the truth:
- Success requires a known protected URL to load without redirecting to an auth page,
  AND either an authenticated indicator is present or the login form is gone with no visible error.
- Failure returns explicit reason codes:
  SUCCESS, BAD_CREDENTIALS, NEEDS_OTP, NEEDS_CAPTCHA, NEEDS_EMAIL_VERIFICATION, SSO_ONLY, SITE_ERROR, UNKNOWN.
"""

import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.engine.browser.session import BrowserSession

logger = logging.getLogger(__name__)


class AuthReasonCode:
    SUCCESS = "SUCCESS"
    BAD_CREDENTIALS = "BAD_CREDENTIALS"
    NEEDS_OTP = "NEEDS_OTP"
    NEEDS_CAPTCHA = "NEEDS_CAPTCHA"
    NEEDS_EMAIL_VERIFICATION = "NEEDS_EMAIL_VERIFICATION"
    SSO_ONLY = "SSO_ONLY"
    SITE_ERROR = "SITE_ERROR"
    UNKNOWN = "UNKNOWN"


# Explicit regex patterns for failure classifications
BAD_CREDENTIALS_PATTERNS = [
    r"invalid (username|password|credentials|email)",
    r"incorrect (username|password|credentials|email)",
    r"wrong (username|password|credentials)",
    r"user not found",
    r"authentication failed",
    r"bad credentials",
    r"unauthorized",
    r"could not verify your credentials",
    r"credentials do not match",
]

NEEDS_OTP_PATTERNS = [
    r"enter (the )?(two-factor|2fa|authenticator|verification|one-time|sms|totp|\d-digit) code",
    r"(two-factor|2fa|totp) (authentication )?(code|required|prompt|challenge)",
    r"authenticator code",
    r"verification code",
    r"one-time (code|password)",
    r"enter your code",
    r"sms code",
]

NEEDS_CAPTCHA_PATTERNS = [
    r"captcha",
    r"recaptcha",
    r"hcaptcha",
    r"cf-turnstile",
    r"turnstile",
    r"verify (that )?you are human",
    r"complete the security check",
    r"bot detection",
]

NEEDS_EMAIL_VERIFICATION_PATTERNS = [
    r"verify your email",
    r"check your inbox",
    r"email confirmation required",
    r"we sent an activation link",
    r"confirm your email address",
    r"unverified email",
]

SSO_ONLY_PATTERNS = [
    r"sso only",
    r"single sign-on only",
    r"organization requires sso",
    r"use single sign-on",
    r"saml login required",
    r"log in with your company account",
]

SITE_ERROR_PATTERNS = [
    r"internal server error",
    r"500 internal",
    r"502 bad gateway",
    r"503 service unavailable",
    r"something went wrong on our end",
    r"an unexpected error occurred",
]

AUTH_URL_PATTERNS = [
    r"/login\b",
    r"/signin\b",
    r"/sign-in\b",
    r"/auth\b",
    r"/authenticate\b",
]

AUTHENTICATED_INDICATORS = [
    r"\b(sign out|logout|log out)\b",
    r"\bwelcome\b",
    r"\bdashboard\b",
    r"\bmy account\b",
    r"\buser profile\b",
    r"\bsettings\b",
]


async def verify_authenticated(
    browser: BrowserSession,
    capability: Any = None,
    target_url: str | None = None,
) -> tuple[bool, str]:
    """Verify whether a browser session is genuinely authenticated.

    Args:
        browser: Active BrowserSession.
        capability: Optional AuthCapability containing login_url, success_url_pattern, etc.
        target_url: Optional URL to test access against.

    Returns:
        (is_authenticated, reason_code)
    """
    if not browser or not browser.page:
        return False, AuthReasonCode.UNKNOWN

    page = browser.page
    current_url = page.url or ""

    # 1. Inspect page text and DOM for explicit failure reason codes
    try:
        body_text = await page.inner_text("body", timeout=1500)
    except Exception:
        body_text = ""

    body_lower = body_text.lower()

    # Site Error (500 / 502 / 503)
    if any(re.search(p, body_lower) for p in SITE_ERROR_PATTERNS):
        return False, AuthReasonCode.SITE_ERROR

    # Captcha challenge present
    if any(re.search(p, body_lower) for p in NEEDS_CAPTCHA_PATTERNS):
        return False, AuthReasonCode.NEEDS_CAPTCHA

    # Explicit bad credentials error
    if any(re.search(p, body_lower) for p in BAD_CREDENTIALS_PATTERNS):
        return False, AuthReasonCode.BAD_CREDENTIALS

    # 2. Check if login form is still visible
    login_form_visible = False
    try:
        pwd_input = await page.query_selector("input[type='password']")
        if pwd_input and await pwd_input.is_visible():
            login_form_visible = True
        else:
            frames = getattr(page, "frames", None)
            if isinstance(frames, (list, tuple)):
                for frame in frames:
                    if frame == page.main_frame:
                        continue
                    f_pwd = await frame.query_selector("input[type='password']")
                    if f_pwd and await f_pwd.is_visible():
                        login_form_visible = True
                        break
    except Exception:
        pass

    # OTP prompt active
    has_otp_field = False
    try:
        otp_el = (
            await page.query_selector("input[autocomplete='one-time-code']")
            or await page.query_selector("input[inputmode='numeric'][maxlength='6']")
            or await page.query_selector("input[name='otp'], input[id='otp']")
        )
        if not otp_el and not login_form_visible:
            otp_el = await page.query_selector("input[name='code']")
        if otp_el and await otp_el.is_visible():
            has_otp_field = True
    except Exception:
        pass

    has_otp_prompt = has_otp_field or (
        any(re.search(p, body_lower) for p in NEEDS_OTP_PATTERNS)
        and not any(re.search(p, body_lower) for p in AUTHENTICATED_INDICATORS)
        and not any(k in body_lower for k in ("successful", "verified", "passed"))
    )
    if has_otp_prompt and not login_form_visible:
        return False, AuthReasonCode.NEEDS_OTP

    # Email verification required
    if any(re.search(p, body_lower) for p in NEEDS_EMAIL_VERIFICATION_PATTERNS):
        return False, AuthReasonCode.NEEDS_EMAIL_VERIFICATION

    # SSO Only constraint
    if any(re.search(p, body_lower) for p in SSO_ONLY_PATTERNS):
        return False, AuthReasonCode.SSO_ONLY

    # 3. Determine if current page is on an auth URL
    parsed_current = urlparse(current_url)
    current_path = parsed_current.path.lower()
    is_on_auth_url = any(re.search(p, current_path) for p in AUTH_URL_PATTERNS)

    # 4. If target_url or protected URL is specified and different from current, verify navigation
    protected_url = target_url or getattr(capability, "target_url", None)
    if not protected_url and getattr(capability, "success_url_pattern", None):
        pat = capability.success_url_pattern
        if pat.startswith("/") and not any(c in pat for c in ("*", "+", "?", "(", "|")):
            protected_url = pat

    # If the user is on an authenticated page or navigated past auth:
    has_auth_indicator = any(re.search(p, body_lower) for p in AUTHENTICATED_INDICATORS)

    # Check cookies/tokens in context
    try:
        ctx = getattr(browser, "context", None)
        if ctx is None and hasattr(browser, "page") and browser.page:
            ctx = getattr(browser.page, "context", None)
        cookies = await ctx.cookies() if ctx else []
        has_session_cookie = any(
            any(k in c["name"].lower() for k in ("session", "token", "auth", "jwt", "sid"))
            for c in cookies
        )
    except Exception:
        has_session_cookie = False

    # Positive authentication condition:
    # 1. Not on an auth URL, AND
    # 2. Login password form is NOT visible, AND
    # 3. Either an authenticated indicator text is present, session cookie exists, or custom protected content loads
    if not is_on_auth_url and not login_form_visible:
        if has_auth_indicator or has_session_cookie or body_text:
            return True, AuthReasonCode.SUCCESS

    # If login form is still visible on an auth URL:
    if login_form_visible and is_on_auth_url:
        # Check if an error message container is populated
        try:
            error_el = await page.query_selector(".error, .alert-danger, [role='alert']")
            if error_el and await error_el.is_visible():
                err_text = (await error_el.inner_text()).strip()
                if err_text:
                    return False, AuthReasonCode.BAD_CREDENTIALS
            frames = getattr(page, "frames", None)
            if isinstance(frames, (list, tuple)):
                for frame in frames:
                    if frame == page.main_frame:
                        continue
                    f_err = await frame.query_selector(".error, .alert-danger, [role='alert'], #frameError")
                    if f_err and await f_err.is_visible():
                        f_err_text = (await f_err.inner_text()).strip()
                        if f_err_text:
                            return False, AuthReasonCode.BAD_CREDENTIALS
        except Exception:
            pass
        return False, AuthReasonCode.BAD_CREDENTIALS

    # If redirected back to login without explicit error text
    if is_on_auth_url:
        return False, AuthReasonCode.UNKNOWN

    # If not on auth URL and form is gone, treat as success
    if not login_form_visible:
        return True, AuthReasonCode.SUCCESS

    return False, AuthReasonCode.UNKNOWN
