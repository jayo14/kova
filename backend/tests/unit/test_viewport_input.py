import asyncio
import time
from unittest.mock import AsyncMock, patch
import pytest
from playwright.async_api import async_playwright

from app.engine.execution.runner import FlowRunner
from app.engine.execution.control import queue_user_input


@pytest.mark.asyncio
async def test_one_human_click_means_exactly_one_page_click():
    pw = await async_playwright().start()
    browser_instance = await pw.chromium.launch(headless=True)
    page = await browser_instance.new_page()

    try:
        await page.set_content("""
            <html>
                <body>
                    <button id="btn" style="width:100px;height:50px;" onclick="window.clicks = (window.clicks || 0) + 1">Button</button>
                </body>
            </html>
        """)

        class FakeBrowserSession:
            def __init__(self, page):
                self.page = page

        browser_session = FakeBrowserSession(page)
        runner = FlowRunner()
        exec_id = "test-exec-click-dedup"

        # Simulate a human click: mouse_down, mouse_up, and a redundant click within 50ms
        await queue_user_input(exec_id, {"kind": "mouse_down", "x": 50, "y": 25, "button": 0})
        await queue_user_input(exec_id, {"kind": "mouse_up", "x": 50, "y": 25, "button": 0})
        await queue_user_input(exec_id, {"kind": "click", "x": 50, "y": 25})

        await runner._process_user_input(browser_session, exec_id)

        clicks = await page.evaluate("window.clicks || 0")
        assert clicks == 1, f"Expected exactly 1 click on page, got {clicks}"

    finally:
        await browser_instance.close()
        await pw.stop()


@pytest.mark.asyncio
async def test_named_keys_hello_backspace_x_produces_hellx():
    pw = await async_playwright().start()
    browser_instance = await pw.chromium.launch(headless=True)
    page = await browser_instance.new_page()

    try:
        await page.set_content("""
            <html>
                <body>
                    <input id="input-box" type="text" autofocus />
                </body>
            </html>
        """)
        await page.focus("#input-box")

        class FakeBrowserSession:
            def __init__(self, page):
                self.page = page

        browser_session = FakeBrowserSession(page)
        runner = FlowRunner()
        exec_id = "test-exec-named-keys"

        # Type 'h', 'e', 'l', 'l', 'o'
        for char in "hello":
            await queue_user_input(exec_id, {"kind": "key_down", "key": char})
            await queue_user_input(exec_id, {"kind": "key_up", "key": char})

        # Press Backspace (named key)
        await queue_user_input(exec_id, {"kind": "key_down", "key": "Backspace"})
        await queue_user_input(exec_id, {"kind": "key_up", "key": "Backspace"})

        # Type 'x'
        await queue_user_input(exec_id, {"kind": "key_down", "key": "x"})
        await queue_user_input(exec_id, {"kind": "key_up", "key": "x"})

        await runner._process_user_input(browser_session, exec_id)

        val = await page.input_value("#input-box")
        assert val == "hellx", f"Expected input value 'hellx', got '{val}'"

    finally:
        await browser_instance.close()
        await pw.stop()
