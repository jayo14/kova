"""Authentication barrier detection and automated authentication helpers.

Provides shared routines for detecting when a target URL is behind an
auth wall (e.g. /settings redirecting to /signin), and intelligently
logging in using available test account credentials.
"""

import asyncio
import logging
import re
from urllib.parse import urlparse
from typing import Any

logger = logging.getLogger(__name__)

AUTH_URL_PATTERNS = [
    r"/sign-?in\b",
    r"/log-?in\b",
    r"/auth\b",
    r"/session\b",
    r"/register\b",
    r"/sign-?up\b",
    r"/accounts/login\b",
    r"/accounts/signin\b",
    r"/user/login\b",
    r"/app/login\b",
]


def is_auth_url(url: str | None) -> bool:
    """Return True if the URL path matches common authentication endpoints."""
    if not url:
        return False
    path = urlparse(url).path.lower()
    return any(re.search(pat, path) for pat in AUTH_URL_PATTERNS)


async def is_auth_page(page: Any, url: str | None = None) -> bool:
    """Return True if the page URL or DOM indicates an authentication barrier."""
    current_url = url or getattr(page, "url", "")
    if is_auth_url(current_url):
        return True

    # Check for visible password input
    try:
        pwd_count = await page.locator('input[type="password"]').count()
        if pwd_count > 0:
            first_pwd = page.locator('input[type="password"]').first
            if await first_pwd.is_visible(timeout=500):
                return True
    except Exception:
        pass

    return False


def is_auth_barrier(expected_url: str | None, current_url: str | None) -> bool:
    """Detect whether a navigation was redirected to an auth wall.

    True when the expected destination was NOT an auth page, but the actual
    resulting URL is an auth page.
    """
    if not current_url:
        return False
    expected_is_auth = is_auth_url(expected_url)
    current_is_auth = is_auth_url(current_url)
    return current_is_auth and not expected_is_auth


async def find_submit_button(page: Any, password_input: Any = None) -> Any:
    """Locate the authentic form submit button, avoiding OAuth/SSO buttons."""
    oauth_keywords = ["google", "github", "apple", "microsoft", "facebook", "twitter", "sso", "saml", "okta"]
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Sign In")',
        'button:has-text("Log in")',
        'button:has-text("Log In")',
        'button:has-text("Continue")',
        'button:has-text("Submit")',
    ]

    for sel in submit_selectors:
        try:
            buttons = await page.locator(sel).all()
            for btn in buttons:
                try:
                    if not await btn.is_visible(timeout=500):
                        continue
                    txt = (await btn.inner_text(timeout=500) or "").lower()
                    if any(oa in txt for oa in oauth_keywords):
                        continue
                    return btn
                except Exception:
                    continue
        except Exception:
            continue
    return None


async def perform_login(
    page: Any,
    email: str,
    password: str,
    name: str | None = None,
    is_signup: bool = False,
) -> tuple[bool, str]:
    """Fill login or registration form, submit credentials, and wait for session.

    Handles React/SPA controlled inputs by dispatching synthetic change events,
    auto-checks terms checkboxes, and handles form submission.
    """
    if not email or not password:
        return False, "Missing email or password credentials."

    initial_url = getattr(page, "url", "")

    # 1. Locate name input if present
    name_selector = (
        'input[name="name" i], '
        'input[name*="full_name" i], '
        'input[name*="fullname" i], '
        'input[autocomplete="name" i], '
        'input[placeholder*="name" i], '
        'input[aria-label*="name" i], '
        'input[id*="name" i]:not([id*="user" i])'
    )
    try:
        name_loc = page.locator(name_selector).first
        if await name_loc.is_visible(timeout=800):
            display_name = name or "Kova Tester"
            await name_loc.focus()
            await name_loc.fill(display_name)
            await name_loc.evaluate(
                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
    except Exception:
        pass

    # 2. Locate email/username input
    email_selector = (
        'input[type="email"], '
        'input[name="email" i], '
        'input[name="username" i], '
        'input[autocomplete="email" i], '
        'input[autocomplete="username" i], '
        '#email, #username, '
        'input[placeholder*="email" i], '
        'input[placeholder*="username" i], '
        'input[aria-label*="email" i], '
        'input[aria-label*="username" i]'
    )
    email_input = None
    try:
        loc = page.locator(email_selector).first
        if await loc.is_visible(timeout=1500):
            email_input = loc
    except Exception:
        pass

    if not email_input:
        try:
            loc = page.locator(
                'input:not([type="password"]):not([type="hidden"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"])'
            ).first
            if await loc.is_visible(timeout=1000):
                email_input = loc
        except Exception:
            pass

    # 3. Locate password input
    password_selector = (
        'input[type="password"], '
        'input[name="password" i], '
        'input[autocomplete*="password" i], '
        '#password, '
        'input[placeholder*="password" i], '
        'input[aria-label*="password" i]'
    )
    password_input = None
    try:
        loc = page.locator(password_selector).first
        if await loc.is_visible(timeout=1500):
            password_input = loc
    except Exception:
        pass

    if not email_input or not password_input:
        return False, "Could not find email or password input fields on the page."

    try:
        # Focus and fill email
        await email_input.focus()
        await email_input.fill(email)
        try:
            await email_input.evaluate(
                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
        except Exception:
            pass

        # Focus and fill password (handles repeat password / confirm password if present)
        try:
            pwd_locs = await page.locator(password_selector).all()
            for p_loc in pwd_locs:
                try:
                    if await p_loc.is_visible(timeout=500):
                        await p_loc.focus()
                        await p_loc.fill(password)
                        await p_loc.evaluate(
                            "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                        )
                except Exception:
                    pass
        except Exception:
            await password_input.focus()
            await password_input.fill(password)
            try:
                await password_input.evaluate(
                    "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                )
            except Exception:
                pass

        # Agree to terms if checkbox exists
        terms_selector = (
            'input[type="checkbox"][name*="term" i], '
            'input[type="checkbox"][name*="agree" i], '
            'input[type="checkbox"][id*="term" i], '
            'input[type="checkbox"][id*="agree" i], '
            'input[type="checkbox"][aria-label*="term" i], '
            'input[type="checkbox"][aria-label*="agree" i]'
        )
        try:
            terms_cb = page.locator(terms_selector).first
            if await terms_cb.is_visible(timeout=500):
                if not await terms_cb.is_checked():
                    await terms_cb.check()
        except Exception:
            pass

        await asyncio.sleep(0.3)

        # Submit form
        submit_btn = await find_submit_button(page, password_input)
        submitted = False
        if submit_btn:
            try:
                await submit_btn.scroll_into_view_if_needed(timeout=1500)
                await submit_btn.click(timeout=3000)
                submitted = True
            except Exception:
                try:
                    await submit_btn.click(force=True, timeout=2000)
                    submitted = True
                except Exception:
                    pass

        if not submitted:
            # Fallback: press Enter on password field
            try:
                await password_input.press("Enter")
                submitted = True
            except Exception:
                pass

        if not submitted:
            return False, "Could not submit login form (no active submit button found)."

        # Wait for navigation or state change
        for _ in range(12):  # up to 6 seconds
            await asyncio.sleep(0.5)
            curr = getattr(page, "url", "")
            if curr != initial_url and not is_auth_url(curr):
                return True, f"Authentication succeeded, redirected to {curr}"

        # Check if auth error message is visible
        error_locators = [
            '[role="alert"]',
            '.error-message',
            '.alert-error',
            'p:has-text("Invalid credentials")',
            'p:has-text("incorrect password")',
            'p:has-text("User not found")',
        ]
        for el_sel in error_locators:
            try:
                err_el = page.locator(el_sel).first
                if await err_el.is_visible(timeout=300):
                    err_txt = await err_el.inner_text(timeout=300)
                    return False, f"Login rejected by application: {err_txt.strip()}"
            except Exception:
                pass

        # If URL hasn't changed, check if password input has disappeared (SPA state change)
        try:
            if await page.locator('input[type="password"]').count() == 0:
                return True, "Authentication succeeded (login form dismissed)."
        except Exception:
            pass

        return False, f"Submitted credentials but page remained on auth URL: {initial_url}"

    except Exception as e:
        logger.warning("perform_login failed with exception: %s", e)
        return False, f"Error during login: {str(e)[:150]}"
