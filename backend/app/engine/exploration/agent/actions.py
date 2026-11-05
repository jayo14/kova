"""Deterministic execution handlers for exploration agent actions.

Handles navigation, clicks, form filling, submissions, and authentication
interactions safely and deterministically across modern web applications.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urljoin

from app.engine.exploration.agent.policy import is_dangerous_control, is_safe_to_click
from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction

logger = logging.getLogger(__name__)


async def execute_action(
    page: Any,
    proposal: AgentActionProposal,
    credentials: dict[str, Any] | None = None,
    history: list[str] | None = None,
) -> tuple[bool, str]:
    """Execute a validated exploration action on the browser page.

    Returns:
        (success: bool, observation_summary: str)
    """
    action = proposal.action
    target = proposal.target or {}

    try:
        if action == ExplorationAction.OPEN_LINK:
            return await execute_open_link(page, target, history=history)
        if action in (
            ExplorationAction.CLICK_CONTROL,
            ExplorationAction.OPEN_MENU_OR_TAB,
            ExplorationAction.EXPAND_ACCORDION,
        ):
            return await execute_click(page, target)
        if action == ExplorationAction.FILL_INPUTS:
            return await execute_fill_inputs(page, target)
        if action == ExplorationAction.SUBMIT_FORM:
            return await execute_submit_form(page, target)
        if action == ExplorationAction.AUTHENTICATE:
            return await execute_authenticate(page, target, credentials)
        if action == ExplorationAction.SCROLL_TO_LOAD_MORE:
            return await execute_scroll(page)
        if action == ExplorationAction.GO_BACK:
            return await execute_go_back(page, history=history)
        if action == ExplorationAction.DISMISS_INTERRUPTION:
            return await execute_dismiss_interruption(page, target)
        if action == ExplorationAction.COMPLETE_INTERRUPTION:
            return await execute_complete_interruption(page, target)

        return False, f"Unsupported action type: {action}"
    except Exception as exc:
        logger.debug("Action %s execution failed: %s", action, exc, exc_info=True)
        return False, f"Action execution failed: {exc}"


async def execute_open_link(
    page: Any,
    target: dict[str, Any],
    history: list[str] | None = None,
) -> tuple[bool, str]:
    url = target.get("url") or target.get("href")
    if not url:
        return False, "No URL specified for open_link"

    try:
        current = getattr(page, "url", None)
        if url.startswith("/") and current:
            url = urljoin(current, url)
        if current and history is not None:
            history.append(str(current))

        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if hasattr(page, "wait_for_load_state"):
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                pass
        current = getattr(page, "url", url)
        return True, f"Navigated to {current}"
    except Exception as exc:
        return False, f"Navigation to {url} failed: {exc}"


async def execute_click(page: Any, target: dict[str, Any]) -> tuple[bool, str]:
    name = target.get("text") or target.get("name") or ""
    if not is_safe_to_click(name, target):
        return False, f"Control '{name}' rejected by safety policy"

    selector = target.get("selector")
    if selector:
        try:
            locator = page.locator(selector)
            if hasattr(locator, "first"):
                locator = locator.first
            if await locator.is_visible(timeout=1000):
                if hasattr(locator, "scroll_into_view_if_needed"):
                    try:
                        await locator.scroll_into_view_if_needed(timeout=1000)
                    except Exception:
                        pass
                await locator.click(timeout=5000)
                return True, f"Clicked control via selector '{selector}'"
        except Exception:
            pass

    if name:
        try:
            locator = page.get_by_text(str(name), exact=False)
            if hasattr(locator, "first"):
                locator = locator.first
            if await locator.is_visible(timeout=1000):
                if hasattr(locator, "scroll_into_view_if_needed"):
                    try:
                        await locator.scroll_into_view_if_needed(timeout=1000)
                    except Exception:
                        pass
                await locator.click(timeout=5000)
                return True, f"Clicked control with text '{name}'"
        except Exception:
            pass

        if hasattr(page, "get_by_role"):
            try:
                locator = page.get_by_role("button", name=str(name))
                if hasattr(locator, "first"):
                    locator = locator.first
                if await locator.is_visible(timeout=1000):
                    await locator.click(timeout=5000)
                    return True, f"Clicked button role '{name}'"
            except Exception:
                pass

    return False, f"Could not find or click target control '{name or selector}'"


async def execute_fill_inputs(page: Any, target: dict[str, Any]) -> tuple[bool, str]:
    inputs = target.get("inputs") or []
    if not inputs and "selector" in target and "value" in target:
        inputs = [{"selector": target["selector"], "value": target["value"]}]

    if not inputs:
        return False, "No inputs provided to fill"

    filled_count = 0
    for item in inputs:
        selector = item.get("selector")
        name = item.get("name")
        value = str(item.get("value", ""))

        loc = None
        if selector:
            try:
                l = page.locator(selector)
                if hasattr(l, "first"):
                    l = l.first
                if await l.is_visible(timeout=1000):
                    loc = l
            except Exception:
                pass

        if loc is None and name:
            for s in [f'input[name="{name}"]', f'textarea[name="{name}"]', f'[placeholder*="{name}" i]']:
                try:
                    l = page.locator(s)
                    if hasattr(l, "first"):
                        l = l.first
                    if await l.is_visible(timeout=500):
                        loc = l
                        break
                except Exception:
                    pass

        if loc is not None:
            try:
                if hasattr(loc, "focus"):
                    await loc.focus()
                await loc.fill(value)
                if hasattr(loc, "evaluate"):
                    await loc.evaluate(
                        "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                    )
                filled_count += 1
            except Exception as e:
                logger.debug("Failed filling input %s: %s", selector or name, e)

    return filled_count > 0, f"Filled {filled_count} form input(s)"


async def execute_submit_form(page: Any, target: dict[str, Any]) -> tuple[bool, str]:
    submit_selector = target.get("submit_selector") or target.get("selector")
    if submit_selector:
        try:
            btn = page.locator(submit_selector)
            if hasattr(btn, "first"):
                btn = btn.first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=5000)
                return True, f"Submitted form via button selector '{submit_selector}'"
        except Exception:
            pass

    # Generic submit button search within active form or page
    for s in [
        'button[type="submit"]',
        'input[type="submit"]',
        'form button:not([type="button"])',
    ]:
        try:
            btn = page.locator(s)
            if hasattr(btn, "first"):
                btn = btn.first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=5000)
                return True, f"Submitted form via generic button '{s}'"
        except Exception:
            pass

    return False, "Could not find a submit button to submit the form"


async def execute_authenticate(
    page: Any,
    target: dict[str, Any],
    credentials: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    creds = credentials or target.get("credentials") or {}
    email = creds.get("email") or creds.get("username") or ""
    password = creds.get("password") or ""

    if not email or not password:
        return False, "Missing username/email or password for authentication"

    # Identify and fill full name if present on registration forms
    name = creds.get("name") or "Kova Tester"
    name_selectors = [
        'input[autocomplete="name" i]',
        'input[placeholder*="name" i]',
        'input[placeholder*="logbook" i]',
        '#su-n',
        'input[id*="name" i]',
        'input[name*="name" i]',
    ]
    for s in name_selectors:
        try:
            nl = page.locator(s)
            if hasattr(nl, "first"):
                nl = nl.first
            if hasattr(nl, "is_visible") and await nl.is_visible(timeout=200):
                if hasattr(nl, "focus"):
                    await nl.focus()
                await nl.fill(name)
                if hasattr(nl, "evaluate"):
                    await nl.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
                break
        except Exception:
            pass

    # Identify email/user input
    email_selectors = [
        'input[type="email"]',
        '#su-e',
        '#email',
        'input[name*="email" i]',
        'input[name*="user" i]',
        'input[autocomplete="email"]',
        'input[autocomplete="username"]',
        'input[placeholder*="email" i]',
    ]
    email_loc = None
    for s in email_selectors:
        try:
            l = page.locator(s)
            if hasattr(l, "first"):
                l = l.first
            if hasattr(l, "is_visible") and await l.is_visible(timeout=500):
                email_loc = l
                break
        except Exception:
            pass

    if not email_loc:
        return False, "Could not find email/username input field on the page"

    try:
        if hasattr(email_loc, "focus"):
            await email_loc.focus()
        await email_loc.fill(email)
        if hasattr(email_loc, "evaluate"):
            await email_loc.evaluate(
                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
    except Exception as exc:
        return False, f"Failed filling username/email: {exc}"

    # Identify password input
    password_selectors = [
        'input[type="password"]',
        '#su-p',
        '#password',
        'input[name*="password" i]',
        'input[autocomplete*="password"]',
        'input[placeholder*="password" i]',
    ]
    pwd_loc = None
    for s in password_selectors:
        try:
            l = page.locator(s)
            if hasattr(l, "first"):
                l = l.first
            if hasattr(l, "is_visible") and await l.is_visible(timeout=500):
                pwd_loc = l
                break
        except Exception:
            pass

    if not pwd_loc:
        return False, "Could not locate password field on authentication screen"

    try:
        if hasattr(pwd_loc, "focus"):
            await pwd_loc.focus()
        await pwd_loc.fill(password)
        if hasattr(pwd_loc, "evaluate"):
            await pwd_loc.evaluate(
                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
    except Exception as exc:
        return False, f"Failed filling password: {exc}"

    # Fill confirm password if present on registration forms
    confirm_pwd_selectors = [
        'input[name*="confirm" i]',
        'input[id*="confirm" i]',
        'input[placeholder*="confirm" i]',
        'input[autocomplete="new-password"] + input',
    ]
    for cs in confirm_pwd_selectors:
        try:
            cloc = page.locator(cs)
            if hasattr(cloc, "first"):
                cloc = cloc.first
            if hasattr(cloc, "is_visible") and await cloc.is_visible(timeout=200):
                if hasattr(cloc, "focus"):
                    await cloc.focus()
                await cloc.fill(password)
                if hasattr(cloc, "evaluate"):
                    await cloc.evaluate(
                        "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                    )
                break
        except Exception:
            pass

    # Agree to terms checkbox if required
    terms_selectors = [
        '#su-t',
        'input[type="checkbox"][name*="term" i]',
        'input[type="checkbox"][name*="agree" i]',
        'input[type="checkbox"][id*="term" i]',
        'input[type="checkbox"]',
    ]
    for ts in terms_selectors:
        try:
            tc = page.locator(ts)
            if hasattr(tc, "first"):
                tc = tc.first
            if hasattr(tc, "is_visible") and await tc.is_visible(timeout=200):
                if hasattr(tc, "is_checked") and not await tc.is_checked():
                    await tc.check()
                break
        except Exception:
            pass

    # Submit login or registration (explicitly avoiding OAuth buttons)
    submit_success = False
    candidate_submits = [
        'button[type="submit"]',
        'button:has-text("Create account")',
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
        'input[type="submit"]',
    ]
    for cs in candidate_submits:
        try:
            btn = page.locator(cs)
            if hasattr(btn, "first"):
                btn = btn.first
            if hasattr(btn, "is_visible") and await btn.is_visible(timeout=300):
                # Verify it does not say Google / GitHub / etc.
                txt = (await btn.inner_text() if hasattr(btn, "inner_text") else "").lower()
                if not any(oa in txt for oa in ["google", "github", "apple", "microsoft", "sso"]):
                    if hasattr(btn, "click"):
                        await btn.click(timeout=5000)
                        submit_success = True
                        break
        except Exception:
            pass

    if not submit_success:
        submit_success, msg = await execute_submit_form(page, target)

    if not submit_success and hasattr(pwd_loc, "press"):
        try:
            await pwd_loc.press("Enter")
            submit_success = True
        except Exception:
            pass

    if not submit_success:
        return False, "Failed submitting authentication form"

    # Allow brief settling for navigation or SPA redirection
    current_url = getattr(page, "url", None)
    try:
        if hasattr(page, "wait_for_load_state"):
            await page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass

    # Poll up to 6 seconds for client-side SPA navigation / auth redirect
    if current_url:
        for _ in range(30):
            await asyncio.sleep(0.2)
            new_url = getattr(page, "url", current_url)
            if new_url != current_url:
                break

    return True, "Submitted credentials for authentication"


async def execute_scroll(page: Any) -> tuple[bool, str]:
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        return True, "Scrolled to load more content"
    except Exception as exc:
        return False, f"Scroll failed: {exc}"


async def execute_go_back(
    page: Any,
    history: list[str] | None = None,
) -> tuple[bool, str]:
    try:
        res = await page.go_back(wait_until="domcontentloaded", timeout=10000)
        if res is not None:
            if history:
                history.pop()
            return True, "Navigated back in browser history"
        return False, "Browser could not go back"
    except Exception as exc:
        return False, f"Go back failed: {exc}"


async def execute_dismiss_interruption(
    page: Any,
    target: dict[str, Any],
) -> tuple[bool, str]:
    """Dismiss an interface interruption using available controls, backdrop, or Escape."""
    title = target.get("dialog_title") or "dialog"
    selector = target.get("selector")
    text = target.get("text") or target.get("name")

    # 1. Click explicit control if identified
    if selector:
        try:
            loc = page.locator(selector)
            if hasattr(loc, "first"):
                loc = loc.first
            if await loc.is_visible(timeout=1000):
                await loc.click(timeout=3000)
                await asyncio.sleep(0.4)
                return True, f"Dismissed interruption '{title}' via control {selector}"
        except Exception:
            pass

    if text:
        try:
            clean = str(text).replace("'", "\\'")
            loc = page.locator(f"button:has-text('{clean}'), a:has-text('{clean}'), [role='button']:has-text('{clean}')")
            if hasattr(loc, "first"):
                loc = loc.first
            if await loc.is_visible(timeout=800):
                await loc.click(timeout=3000)
                await asyncio.sleep(0.4)
                return True, f"Dismissed interruption '{title}' via '{text}' button"
        except Exception:
            pass

    # 2. Try common close buttons
    close_candidates = [
        "button:has-text('Got it')",
        "button:has-text('Close')",
        "button:has-text('Dismiss')",
        "button:has-text('Not now')",
        "button:has-text('Maybe later')",
        "button:has-text('Skip')",
        "button[aria-label*='close' i]",
        "button[aria-label*='dismiss' i]",
        "[aria-label*='Close' i]",
        ".close",
        "[class*='close']",
    ]
    for cs in close_candidates:
        try:
            loc = page.locator(cs)
            if hasattr(loc, "first"):
                loc = loc.first
            if await loc.is_visible(timeout=300):
                await loc.click(timeout=2000)
                await asyncio.sleep(0.4)
                return True, f"Dismissed interruption '{title}' via {cs}"
        except Exception:
            pass

    # 3. Try Escape key
    try:
        if hasattr(page, "keyboard") and hasattr(page.keyboard, "press"):
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.4)
            return True, f"Dismissed interruption '{title}' via Escape key"
    except Exception:
        pass

    return False, f"Could not dismiss interruption '{title}'"


async def execute_complete_interruption(
    page: Any,
    target: dict[str, Any],
) -> tuple[bool, str]:
    """Complete a required setup interaction by filling synthetic inputs and submitting."""
    title = target.get("dialog_title") or "setup"
    fields = target.get("fields") or {}

    for sel, val in fields.items():
        try:
            loc = page.locator(sel)
            if hasattr(loc, "first"):
                loc = loc.first
            if await loc.is_visible(timeout=500):
                if isinstance(val, bool):
                    if val and hasattr(loc, "check"):
                        await loc.check()
                else:
                    if hasattr(loc, "fill"):
                        await loc.fill(str(val))
        except Exception:
            continue

    # Click submit or action button
    selector = target.get("selector")
    if selector:
        try:
            loc = page.locator(selector)
            if hasattr(loc, "first"):
                loc = loc.first
            if await loc.is_visible(timeout=1000):
                await loc.click(timeout=3000)
                await asyncio.sleep(0.5)
                return True, f"Completed required interaction for '{title}'"
        except Exception:
            pass

    submit_candidates = [
        "button[type='submit']",
        "button:has-text('Continue')",
        "button:has-text('Next')",
        "button:has-text('Save')",
        "button:has-text('Done')",
        "button:has-text('Create')",
    ]
    for cs in submit_candidates:
        try:
            loc = page.locator(cs)
            if hasattr(loc, "first"):
                loc = loc.first
            if await loc.is_visible(timeout=500):
                await loc.click(timeout=2000)
                await asyncio.sleep(0.5)
                return True, f"Submitted required setup '{title}' via {cs}"
        except Exception:
            pass

    return True, f"Completed input entry for '{title}'"
