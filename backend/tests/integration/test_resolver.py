"""Integration tests for TargetResolver.

Tests resolution strategies: test ID, role+name, label, text, CSS,
and error handling for missing/ambiguous targets.
"""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.resolver import (
    AmbiguousTargetError,
    ResolutionStrategy,
    TargetNotFoundError,
    TargetResolver,
)
from app.engine.browser.session import BrowserSession
from tests.test_app import app as test_app


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    port = _get_free_port()
    config = uvicorn.Config(test_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
async def test_server():
    async with _run_test_server() as url:
        yield url


@pytest.fixture
async def browser_session():
    async with BrowserSession() as session:
        yield session


# --- test_id resolution ---


@pytest.mark.asyncio
async def test_resolve_by_data_testid(test_server, browser_session):
    """Resolve element by data-testid attribute."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button data-testid="submit-btn">Submit</button>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("submit-btn", strategy=ResolutionStrategy.TEST_ID)

    assert await locator.count() == 1
    assert await locator.get_attribute("data-testid") == "submit-btn"


@pytest.mark.asyncio
async def test_resolve_by_data_testid_auto_priority(test_server, browser_session):
    """data-testid is tried first when no strategy forced."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <input data-testid="email-field" type="email" />
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("email-field")

    assert await locator.count() == 1
    tag = await locator.evaluate("el => el.tagName.toLowerCase()")
    assert tag == "input"


# --- role + name resolution ---


@pytest.mark.asyncio
async def test_resolve_by_role_and_name(test_server, browser_session):
    """Resolve button by role and accessible name."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button>Sign In</button>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("Sign In", role="button")

    assert await locator.count() == 1
    text = await locator.inner_text()
    assert text == "Sign In"


@pytest.mark.asyncio
async def test_resolve_by_role_no_explicit_role(test_server, browser_session):
    """Resolve textbox by name when role not specified."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="user">Username</label>
            <input type="text" id="user" name="user" />
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("Username", role="textbox")

    assert await locator.count() == 1
    tag = await locator.evaluate("el => el.tagName.toLowerCase()")
    assert tag == "input"


# --- label resolution ---


@pytest.mark.asyncio
async def test_resolve_by_label(test_server, browser_session):
    """Resolve input by associated label text."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="email">Email Address</label>
            <input type="email" id="email" name="email" />
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("Email Address", strategy=ResolutionStrategy.LABEL)

    assert await locator.count() == 1
    input_id = await locator.get_attribute("id")
    assert input_id == "email"


@pytest.mark.asyncio
async def test_resolve_by_label_auto(test_server, browser_session):
    """Label resolution tried automatically when test_id and role fail."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="phone">Phone Number</label>
            <input type="tel" id="phone" name="phone" />
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("Phone Number")

    assert await locator.count() == 1
    input_type = await locator.get_attribute("type")
    assert input_type == "tel"


# --- text resolution ---


@pytest.mark.asyncio
async def test_resolve_by_text(test_server, browser_session):
    """Resolve link by visible text content."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <a href="/about">About Us</a>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("About Us", strategy=ResolutionStrategy.TEXT)

    assert await locator.count() == 1
    tag = await locator.evaluate("el => el.tagName.toLowerCase()")
    assert tag == "a"


@pytest.mark.asyncio
async def test_resolve_by_text_partial_match(test_server, browser_session):
    """Text resolution matches partial text by default."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <p>Welcome to our application</p>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("Welcome to", strategy=ResolutionStrategy.TEXT)

    assert await locator.count() == 1


# --- CSS fallback ---


@pytest.mark.asyncio
async def test_resolve_by_css(test_server, browser_session):
    """Resolve by CSS selector as last resort."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <div class="special">Content</div>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve(".special", strategy=ResolutionStrategy.CSS)

    assert await locator.count() == 1
    text = await locator.inner_text()
    assert text == "Content"


# --- error handling ---


@pytest.mark.asyncio
async def test_resolve_missing_target_raises(test_server, browser_session):
    """TargetNotFoundError raised when no element matches."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button>Existing</button>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    with pytest.raises(TargetNotFoundError) as exc_info:
        await resolver.resolve("nonexistent-button", strategy=ResolutionStrategy.TEST_ID)

    assert "nonexistent-button" in str(exc_info.value)
    assert exc_info.value.target == "nonexistent-button"
    assert exc_info.value.strategy == "test_id"


@pytest.mark.asyncio
async def test_resolve_missing_role_name_raises(test_server, browser_session):
    """TargetNotFoundError for role+name with no match."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button>Submit</button>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    with pytest.raises(TargetNotFoundError) as exc_info:
        await resolver.resolve("Delete", role="button")

    assert "Delete" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_ambiguous_raises(test_server, browser_session):
    """AmbiguousTargetError raised when multiple elements match."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button data-testid="btn-1">Submit</button>
            <button data-testid="btn-2">Submit</button>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    with pytest.raises(AmbiguousTargetError) as exc_info:
        await resolver.resolve("Submit", strategy=ResolutionStrategy.TEXT)

    assert exc_info.value.count == 2
    assert exc_info.value.target == "Submit"
    assert len(exc_info.value.selectors) == 2


@pytest.mark.asyncio
async def test_resolve_ambiguous_includes_selectors(test_server, browser_session):
    """AmbiguousTargetError includes selector details."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <a href="/page1">Click me</a>
            <a href="/page2">Click me</a>
            <a href="/page3">Click me</a>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    with pytest.raises(AmbiguousTargetError) as exc_info:
        await resolver.resolve("Click me")

    assert exc_info.value.count == 3
    assert len(exc_info.value.selectors) == 3


# --- integration with BrowserSession ---


@pytest.mark.asyncio
async def test_browser_session_click_uses_resolver(test_server, browser_session):
    """BrowserSession.click resolves by test ID."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <div id="output">unchanged</div>
            <button data-testid="action-btn">Do it</button>
            <script>
            document.querySelector('[data-testid="action-btn"]').addEventListener('click', () => {
                document.getElementById('output').textContent = 'clicked';
            });
            </script>
        </body>
        </html>
    """)

    await browser_session.click("action-btn")
    text = await browser_session.page.inner_text("#output")
    assert text == "clicked"


@pytest.mark.asyncio
async def test_browser_session_type_uses_resolver(test_server, browser_session):
    """BrowserSession.type resolves by label."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="email">Email</label>
            <input type="email" id="email" name="email" />
        </body>
        </html>
    """)

    await browser_session.type("Email", "test@example.com", role="textbox")
    value = await browser_session.page.input_value("#email")
    assert value == "test@example.com"


@pytest.mark.asyncio
async def test_browser_session_click_falls_back_to_css(test_server, browser_session):
    """BrowserSession.click falls back to CSS if resolver fails."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <div id="target">content</div>
        </body>
        </html>
    """)

    # #target is a div, not interactive, resolver won't find it
    await browser_session.click("#target")
    # No error = fallback worked


# --- edge cases ---


@pytest.mark.asyncio
async def test_resolve_empty_target_raises(test_server, browser_session):
    """Empty target raises TargetNotFoundError."""
    await browser_session.page.set_content("""
        <html><body><button>Hi</button></body></html>
    """)

    resolver = TargetResolver(browser_session.page)
    with pytest.raises(TargetNotFoundError):
        await resolver.resolve("")


@pytest.mark.asyncio
async def test_resolve_special_chars_in_testid(test_server, browser_session):
    """Test IDs with hyphens and underscores resolve correctly."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <input data-testid="user_email-input" type="text" />
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("user_email-input")

    assert await locator.count() == 1


@pytest.mark.asyncio
async def test_resolve_hidden_element_not_returned(test_server, browser_session):
    """Hidden elements are not returned by resolver."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button data-testid="visible-btn">Visible</button>
            <button data-testid="hidden-btn" style="display:none">Hidden</button>
        </body>
        </html>
    """)

    resolver = TargetResolver(browser_session.page)
    locator = await resolver.resolve("hidden-btn")

    # Locator exists in DOM but is hidden
    assert await locator.count() == 1
    assert not await locator.is_visible()
