"""Integration tests for the deterministic verifier.

Tests element_visible, text_visible, url_matches verification types.
"""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.session import BrowserSession
from app.engine.verification.verifier import Verifier
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


# --- element_visible ---


@pytest.mark.asyncio
async def test_element_visible_by_css(test_server, browser_session):
    """Verify element visible by CSS selector."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"css": "#login-btn"}
    })

    assert result.passed is True
    assert len(result.checks) == 1
    assert result.checks[0].type == "element_visible"
    assert result.checks[0].passed is True


@pytest.mark.asyncio
async def test_element_visible_by_role_name(test_server, browser_session):
    """Verify element visible by role and name."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"role": "button", "name": "Sign in"}
    })

    assert result.passed is True


@pytest.mark.asyncio
async def test_element_visible_by_text(test_server, browser_session):
    """Verify element visible by text content."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"text": "Login"}
    })

    assert result.passed is True


@pytest.mark.asyncio
async def test_element_not_visible(test_server, browser_session):
    """Verify element not found fails verification."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"css": "#nonexistent"}
    })

    assert result.passed is False
    assert result.checks[0].passed is False


@pytest.mark.asyncio
async def test_element_hidden(test_server, browser_session):
    """Verify hidden element fails verification."""
    await browser_session.page.set_content("""
        <html><body>
            <button id="hidden" style="display:none">Hidden</button>
        </body></html>
    """)
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"css": "#hidden"}
    })

    assert result.passed is False
    assert result.checks[0].passed is False


@pytest.mark.asyncio
async def test_element_visible_ambiguous(test_server, browser_session):
    """Verify ambiguous element fails verification."""
    await browser_session.page.set_content("""
        <html><body>
            <button>Submit</button>
            <button>Submit</button>
        </body></html>
    """)
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"text": "Submit"}
    })

    assert result.passed is False


# --- text_visible ---


@pytest.mark.asyncio
async def test_text_visible_passes(test_server, browser_session):
    """Verify text visible passes when text exists."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "text_visible": "Login"
    })

    assert result.passed is True
    assert result.checks[0].type == "text_visible"
    assert result.checks[0].passed is True


@pytest.mark.asyncio
async def test_text_visible_fails(test_server, browser_session):
    """Verify text visible fails when text not found."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "text_visible": "Nonexistent Text"
    })

    assert result.passed is False
    assert result.checks[0].passed is False


@pytest.mark.asyncio
async def test_text_visible_on_custom_page(test_server, browser_session):
    """Verify text visible on custom page content."""
    await browser_session.page.set_content("""
        <html><body>
            <h1>Dashboard</h1>
            <p>Welcome back, user!</p>
        </body></html>
    """)
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "text_visible": "Welcome back"
    })

    assert result.passed is True


# --- url_matches ---


@pytest.mark.asyncio
async def test_url_matches_exact(test_server, browser_session):
    """Verify URL matches exactly."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "url_matches": f"{test_server}/login"
    })

    assert result.passed is True
    assert result.checks[0].type == "url_matches"


@pytest.mark.asyncio
async def test_url_matches_contains(test_server, browser_session):
    """Verify URL contains substring."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "url_matches": "127.0.0.1"
    })

    assert result.passed is True


@pytest.mark.asyncio
async def test_url_matches_regex(test_server, browser_session):
    """Verify URL matches regex pattern."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "url_matches": r":\d+/"
    })

    assert result.passed is True


@pytest.mark.asyncio
async def test_url_matches_fails(test_server, browser_session):
    """Verify URL mismatch fails verification."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "url_matches": "https://example.com/different"
    })

    assert result.passed is False


# --- combined checks ---


@pytest.mark.asyncio
async def test_multiple_checks_all_pass(test_server, browser_session):
    """Multiple checks all passing."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"css": "#login-btn"},
        "text_visible": "Login",
        "url_matches": "127.0.0.1",
    })

    assert result.passed is True
    assert len(result.checks) == 3


@pytest.mark.asyncio
async def test_multiple_checks_one_fails(test_server, browser_session):
    """Multiple checks with one failing."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"css": "#login-btn"},
        "text_visible": "Nonexistent Text",
        "url_matches": "127.0.0.1",
    })

    assert result.passed is False
    assert len(result.checks) == 3
    failed_checks = [c for c in result.checks if not c.passed]
    assert len(failed_checks) == 1
    assert failed_checks[0].type == "text_visible"


@pytest.mark.asyncio
async def test_empty_condition_fails_closed(test_server, browser_session):
    """Empty conditions can NEVER pass — fail-closed semantics (readiness §5).

    Historical behavior returned passed=True with zero checks, which let
    missions report COMPLETED without proving anything.
    """
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({})

    assert result.passed is False
    assert len(result.checks) == 1
    assert result.checks[0].type == "empty_condition"


# --- result serialization ---


@pytest.mark.asyncio
async def test_result_to_dict(test_server, browser_session):
    """VerificationResult.to_dict serializes correctly."""
    await browser_session.navigate(f"{test_server}/login")
    verifier = Verifier(browser_session.page)

    result = await verifier.verify({
        "element_visible": {"css": "#login-btn"},
    })

    d = result.to_dict()
    assert d["passed"] is True
    assert len(d["checks"]) == 1
    assert d["checks"][0]["type"] == "element_visible"
    assert d["checks"][0]["passed"] is True
