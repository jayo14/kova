"""Unit tests for resilient locators, drift tolerance, and multi-strategy fallbacks."""

import pytest
from playwright.async_api import async_playwright

from app.engine.browser.actions import Action, ActionTarget, ActionType
from app.engine.browser.executor import ActionExecutor
from app.engine.browser.resolver import TargetResolver
from app.engine.verification.verifier import Verifier


@pytest.fixture
async def page_fixture():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await pw.stop()


@pytest.mark.asyncio
async def test_resolver_self_heals_css_has_text(page_fixture):
    """TargetResolver falls back to text search when CSS has-text selector fails standard match."""
    await page_fixture.set_content("""
        <html>
            <body>
                <button class="btn primary">Confirm Changes</button>
            </body>
        </html>
    """)
    resolver = TargetResolver(page_fixture)
    # Drifted selector from recorded flow or old DOM:
    locator = await resolver.resolve("button:has-text('Confirm Changes')")
    assert await locator.count() == 1
    assert await locator.inner_text() == "Confirm Changes"


@pytest.mark.asyncio
async def test_resolver_self_heals_playwright_text_prefix(page_fixture):
    """TargetResolver handles 'text=...' format cleanly."""
    await page_fixture.set_content("""
        <html>
            <body>
                <a href="/login" class="nav-item">Sign In to Account</a>
            </body>
        </html>
    """)
    resolver = TargetResolver(page_fixture)
    locator = await resolver.resolve("text='Sign In to Account'")
    assert await locator.count() == 1
    assert "Sign In" in await locator.inner_text()


@pytest.mark.asyncio
async def test_resolver_self_heals_drifted_testid_slug(page_fixture):
    """TargetResolver parses slug identifiers (e.g. submit-btn) to find matching button."""
    await page_fixture.set_content("""
        <html>
            <body>
                <!-- Test ID was removed by frontend developers in a refactor -->
                <button class="bg-blue-600">Submit</button>
            </body>
        </html>
    """)
    resolver = TargetResolver(page_fixture)
    locator = await resolver.resolve("submit-btn")
    assert await locator.count() == 1
    assert await locator.inner_text() == "Submit"


@pytest.mark.asyncio
async def test_resolver_prioritizes_visible_when_ambiguous(page_fixture):
    """TargetResolver picks the single visible element when multiple DOM elements match text."""
    await page_fixture.set_content("""
        <html>
            <body>
                <!-- Hidden mobile/drawer duplicate -->
                <button style="display: none;">Checkout</button>
                <!-- Visible desktop button -->
                <button style="display: block;">Checkout</button>
            </body>
        </html>
    """)
    resolver = TargetResolver(page_fixture)
    locator = await resolver.resolve("Checkout")
    assert await locator.is_visible() is True


@pytest.mark.asyncio
async def test_executor_falls_back_when_testid_is_stale(page_fixture):
    """ActionExecutor falls back to role+name or text when test_id no longer exists."""
    await page_fixture.set_content("""
        <html>
            <body>
                <!-- Old test-id was 'checkout-submit', new code only has role and text -->
                <button role="button">Complete Purchase</button>
            </body>
        </html>
    """)
    executor = ActionExecutor(page_fixture)
    # Stale action target recorded with obsolete test_id
    action = Action(
        type=ActionType.CLICK,
        target=ActionTarget(
            test_id="checkout-submit-obsolete",
            role="button",
            name="Complete Purchase",
            text="Complete Purchase",
        ),
    )
    result = await executor.execute(action)
    assert result.get("success") is True
    assert result["result"].get("clicked") is True


@pytest.mark.asyncio
async def test_executor_falls_back_from_invalid_css_to_text(page_fixture):
    """ActionExecutor falls back from outdated CSS selector to visible text."""
    await page_fixture.set_content("""
        <html>
            <body>
                <span class="action-link" onclick="window.clicked = true">Proceed to Dashboard</span>
            </body>
        </html>
    """)
    executor = ActionExecutor(page_fixture)
    action = Action(
        type=ActionType.CLICK,
        target=ActionTarget(
            css=".old-class-renamed-by-tailwind",
            text="Proceed to Dashboard",
        ),
    )
    result = await executor.execute(action)
    assert result.get("success") is True
    assert result["result"].get("clicked") is True
    assert await page_fixture.evaluate("window.clicked") is True


@pytest.mark.asyncio
async def test_verifier_falls_back_when_dict_testid_is_stale(page_fixture):
    """Verifier._resolve_target gracefully falls back when test_id fails but text matches."""
    await page_fixture.set_content("""
        <html>
            <body>
                <div class="alert alert-success">Order placed successfully!</div>
            </body>
        </html>
    """)
    verifier = Verifier(page_fixture)
    target_spec = {
        "test_id": "success-alert-drifted",
        "text": "Order placed successfully!",
    }
    locator = await verifier._resolve_target(target_spec)
    assert await locator.count() == 1
    assert "Order placed successfully" in await locator.inner_text()
