"""Deterministic execution handlers for exploration agent actions.

Handles navigation, clicks, form filling, submissions, and authentication
interactions safely and deterministically across modern web applications.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.engine.exploration.agent.policy import is_dangerous_control, is_safe_to_click
from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction

logger = logging.getLogger(__name__)


async def execute_action(
    page: Any,
    proposal: AgentActionProposal,
    credentials: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Execute a validated exploration action on the browser page.

    Returns:
        (success: bool, observation_summary: str)
    """
    action = proposal.action
    target = proposal.target or {}

    try:
        if action == ExplorationAction.OPEN_LINK:
            return await execute_open_link(page, target)
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
            return await execute_go_back(page)

        return False, f"Unsupported action type: {action}"
    except Exception as exc:
        logger.debug("Action %s execution failed: %s", action, exc, exc_info=True)
        return False, f"Action execution failed: {exc}"


async def execute_open_link(page: Any, target: dict[str, Any]) -> tuple[bool, str]:
    url = target.get("url") or target.get("href")
    if not url:
        return False, "No URL specified for open_link"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
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
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=1500):
                await locator.scroll_into_view_if_needed(timeout=1000)
                await locator.click(timeout=5000)
                await asyncio.sleep(0.3)
                return True, f"Clicked control via selector '{selector}'"
        except Exception:
            pass

    if name:
        try:
            locator = page.get_by_text(str(name), exact=False).first
            if await locator.is_visible(timeout=1500):
                await locator.scroll_into_view_if_needed(timeout=1000)
                await locator.click(timeout=5000)
                await asyncio.sleep(0.3)
                return True, f"Clicked control with text '{name}'"
        except Exception:
            pass

        try:
            locator = page.get_by_role("button", name=str(name)).first
            if await locator.is_visible(timeout=1000):
                await locator.click(timeout=5000)
                await asyncio.sleep(0.3)
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
                l = page.locator(selector).first
                if await l.is_visible(timeout=1000):
                    loc = l
            except Exception:
                pass

        if loc is None and name:
            for s in [f'input[name="{name}"]', f'textarea[name="{name}"]', f'[placeholder*="{name}" i]']:
                try:
                    l = page.locator(s).first
                    if await l.is_visible(timeout=500):
                        loc = l
                        break
                except Exception:
                    pass

        if loc is not None:
            try:
                await loc.focus()
                await loc.fill(value)
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
            btn = page.locator(submit_selector).first
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=5000)
                await asyncio.sleep(0.5)
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
            btn = page.locator(s).first
            if await btn.is_visible(timeout=800):
                await btn.click(timeout=5000)
                await asyncio.sleep(0.5)
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

    # Identify email/user input
    email_selectors = [
        'input[type="email"]',
        'input[name*="email" i]',
        'input[name*="user" i]',
        'input[autocomplete="email"]',
        'input[autocomplete="username"]',
        'input[placeholder*="email" i]',
    ]
    email_loc = None
    for s in email_selectors:
        try:
            l = page.locator(s).first
            if await l.is_visible(timeout=600):
                email_loc = l
                break
        except Exception:
            pass

    if not email_loc:
        return False, "Could not find email/username input field on the page"

    try:
        await email_loc.focus()
        await email_loc.fill(email)
        await email_loc.evaluate(
            "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
        )
    except Exception as exc:
        return False, f"Failed filling username/email: {exc}"

    # Identify password input
    password_selectors = [
        'input[type="password"]',
        'input[name*="password" i]',
        'input[autocomplete*="password"]',
        'input[placeholder*="password" i]',
    ]
    pwd_loc = None
    for s in password_selectors:
        try:
            l = page.locator(s).first
            if await l.is_visible(timeout=600):
                pwd_loc = l
                break
        except Exception:
            pass

    # Handle multi-step login where password appears after next
    if not pwd_loc:
        next_btn = None
        for s in ['button[type="submit"]', 'button:has-text("Next")', 'button:has-text("Continue")']:
            try:
                b = page.locator(s).first
                if await b.is_visible(timeout=500):
                    next_btn = b
                    break
            except Exception:
                pass
        if next_btn:
            try:
                await next_btn.click(timeout=3000)
                await asyncio.sleep(1.0)
                for s in password_selectors:
                    l = page.locator(s).first
                    if await l.is_visible(timeout=2000):
                        pwd_loc = l
                        break
            except Exception:
                pass

    if not pwd_loc:
        return False, "Could not locate password field on authentication screen"

    try:
        await pwd_loc.focus()
        await pwd_loc.fill(password)
        await pwd_loc.evaluate(
            "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
        )
    except Exception as exc:
        return False, f"Failed filling password: {exc}"

    # Submit login
    submit_success, msg = await execute_submit_form(page, target)
    if not submit_success:
        try:
            await pwd_loc.press("Enter")
            submit_success = True
        except Exception:
            pass

    if not submit_success:
        return False, "Failed submitting authentication form"

    await asyncio.sleep(1.5)
    return True, "Submitted credentials for authentication"


async def execute_scroll(page: Any) -> tuple[bool, str]:
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.4)
        return True, "Scrolled to load more content"
    except Exception as exc:
        return False, f"Scroll failed: {exc}"


async def execute_go_back(page: Any) -> tuple[bool, str]:
    try:
        res = await page.go_back(wait_until="domcontentloaded", timeout=10000)
        return res is not None, "Navigated back in browser history"
    except Exception as exc:
        return False, f"Go back failed: {exc}"
