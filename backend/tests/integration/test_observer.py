"""Integration tests for PageObserver.

Tests structured DOM observation against the test app's login form
and custom HTML pages served via the test server.
"""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn

from app.engine.browser.observer import PageObserver
from app.engine.browser.session import BrowserSession
from tests.test_app import app as test_app


def _get_free_port() -> int:
    """Get a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def _run_test_server():
    """Start the test FastAPI app on a free port."""
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
    """Fixture that provides a running test server URL."""
    async with _run_test_server() as url:
        yield url


@pytest.fixture
async def browser_session():
    """Fixture that provides a started BrowserSession, closed after test."""
    async with BrowserSession() as session:
        yield session


@pytest.mark.asyncio
async def test_observe_returns_url_and_title(test_server, browser_session):
    """Observe returns correct url and title."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    assert result["url"].rstrip("/") == test_server.rstrip("/")
    assert result["title"] == "Kova Test App"
    assert "elements" in result
    assert "forms" in result
    assert "text" in result


@pytest.mark.asyncio
async def test_observe_finds_inputs(test_server, browser_session):
    """Observe finds username and password inputs."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    inputs = [e for e in result["elements"] if e["type"] == "input"]
    names = [i["name"] for i in inputs]

    assert "username" in names
    assert "password" in names


@pytest.mark.asyncio
async def test_observe_input_roles(test_server, browser_session):
    """Inputs have role=textbox."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    inputs = [e for e in result["elements"] if e["type"] == "input"]
    for inp in inputs:
        assert inp["role"] == "textbox"


@pytest.mark.asyncio
async def test_observe_finds_button(test_server, browser_session):
    """Observe finds the login button."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    buttons = [e for e in result["elements"] if e["type"] == "button"]
    names = [b["name"] for b in buttons]

    assert "Login" in names


@pytest.mark.asyncio
async def test_observe_button_role(test_server, browser_session):
    """Button has role=button."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    buttons = [e for e in result["elements"] if e["type"] == "button"]
    for btn in buttons:
        assert btn["role"] == "button"


@pytest.mark.asyncio
async def test_observe_selectors_use_id(test_server, browser_session):
    """Elements with IDs get #id selectors."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    username = next(e for e in result["elements"] if e["name"] == "username")
    assert username["selector"] == "#username"


@pytest.mark.asyncio
async def test_observe_labels_from_for_attribute(test_server, browser_session):
    """Labels are extracted from associated <label for='...'> elements."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="email">Email Address</label>
            <input type="email" id="email" name="email" />
            <label for="age">Age</label>
            <input type="number" id="age" name="age" />
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    inputs = {e["name"]: e for e in result["elements"] if e["type"] == "input"}
    assert inputs["email"]["label"] == "Email Address"
    assert inputs["age"]["label"] == "Age"


@pytest.mark.asyncio
async def test_observe_labels_from_nested_label(test_server, browser_session):
    """Labels extracted from label wrapping the input."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label>
                Password
                <input type="password" id="pw" name="pw" />
            </label>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    pw = next(e for e in result["elements"] if e["name"] == "pw")
    assert "Password" in pw["label"]


@pytest.mark.asyncio
async def test_observe_selects_with_options(test_server, browser_session):
    """Observe extracts select elements with their options."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="country">Country</label>
            <select id="country" name="country">
                <option value="us">United States</option>
                <option value="uk">United Kingdom</option>
                <option value="ng">Nigeria</option>
            </select>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    selects = [e for e in result["elements"] if e["type"] == "select"]
    assert len(selects) == 1

    sel = selects[0]
    assert sel["name"] == "country"
    assert sel["label"] == "Country"
    assert sel["role"] == "combobox"
    assert len(sel["options"]) == 3
    assert sel["options"][0]["value"] == "us"
    assert sel["options"][0]["text"] == "United States"


@pytest.mark.asyncio
async def test_observe_textarea(test_server, browser_session):
    """Observe extracts textarea elements."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="bio">Bio</label>
            <textarea id="bio" name="bio" placeholder="Tell us about yourself"></textarea>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    textareas = [e for e in result["elements"] if e["type"] == "textarea"]
    assert len(textareas) == 1
    assert textareas[0]["name"] == "bio"
    assert textareas[0]["label"] == "Bio"
    assert textareas[0]["role"] == "textbox"
    assert textareas[0]["placeholder"] == "Tell us about yourself"


@pytest.mark.asyncio
async def test_observe_forms(test_server, browser_session):
    """Observe extracts form metadata."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <form id="login-form" action="/login" method="post">
                <input type="text" name="user" />
                <input type="password" name="pass" />
                <button type="submit">Go</button>
            </form>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    assert len(result["forms"]) == 1
    form = result["forms"][0]
    assert form["id"] == "login-form"
    assert form["action"] == "/login"
    assert form["method"] == "post"
    assert "user" in form["fields"]
    assert "pass" in form["fields"]


@pytest.mark.asyncio
async def test_observe_links(test_server, browser_session):
    """Observe extracts visible links."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <a href="/about">About Us</a>
            <a href="/contact">Contact</a>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    links = [e for e in result["elements"] if e["type"] == "link"]
    assert len(links) == 2
    names = [l["name"] for l in links]
    assert "About Us" in names
    assert "Contact" in names
    for link in links:
        assert link["role"] == "link"


@pytest.mark.asyncio
async def test_observe_hidden_elements_excluded(test_server, browser_session):
    """Hidden elements are not included in observation."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <input type="text" name="visible" />
            <input type="text" name="hidden" style="display:none" />
            <button name="vis_btn">Visible</button>
            <button name="hid_btn" style="visibility:hidden">Hidden</button>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    names = [e["name"] for e in result["elements"]]
    assert "visible" in names
    assert "hidden" not in names
    # Button name prefers text content over name attr
    button_names = [e["name"] for e in result["elements"] if e["type"] == "button"]
    assert "Visible" in button_names
    assert "Hidden" not in button_names


@pytest.mark.asyncio
async def test_observe_visible_text(test_server, browser_session):
    """Observe extracts visible text from the page."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    assert "Welcome to Kova Test" in result["text"]


@pytest.mark.asyncio
async def test_observe_result_from_session(test_server, browser_session):
    """BrowserSession.observe() delegates to PageObserver and returns same format."""
    await browser_session.navigate(test_server)
    result = await browser_session.observe()

    assert "url" in result
    assert "title" in result
    assert "elements" in result
    assert "forms" in result
    assert "text" in result
    assert result["title"] == "Kova Test App"


@pytest.mark.asyncio
async def test_observe_elements_contain_required_keys(test_server, browser_session):
    """Each element has type, name, label, role, selector."""
    await browser_session.navigate(test_server)
    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    required_keys = {"type", "name", "label", "role", "selector"}
    for element in result["elements"]:
        assert required_keys.issubset(element.keys()), (
            f"Element missing keys: {required_keys - element.keys()}"
        )


@pytest.mark.asyncio
async def test_observe_prefers_aria_label(test_server, browser_session):
    """aria-label is preferred as label over other sources."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <label for="q">Search</label>
            <input type="text" id="q" name="q" aria-label="Find items" />
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    q = next(e for e in result["elements"] if e["name"] == "q")
    assert q["label"] == "Find items"


@pytest.mark.asyncio
async def test_observe_prefers_aria_label_on_button(test_server, browser_session):
    """aria-label on button used as name."""
    await browser_session.page.set_content("""
        <html>
        <body>
            <button id="close" aria-label="Close dialog">X</button>
        </body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    btn = next(e for e in result["elements"] if e["type"] == "button")
    assert btn["name"] == "Close dialog"


@pytest.mark.asyncio
async def test_observe_text_truncated(test_server, browser_session):
    """Visible text is truncated to 5000 chars."""
    long_text = "A" * 6000
    await browser_session.page.set_content(f"""
        <html>
        <body><p>{long_text}</p></body>
        </html>
    """)

    observer = PageObserver(browser_session.page)
    result = await observer.observe()

    assert len(result["text"]) <= 5000
