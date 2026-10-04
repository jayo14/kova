import time
import pytest
from playwright.async_api import async_playwright

from app.engine.browser.executor import ActionExecutor
from app.engine.browser.actions import Action, ActionType


@pytest.mark.asyncio
async def test_non_navigating_click_executes_rapidly_without_5s_delay():
    pw = await async_playwright().start()
    browser_instance = await pw.chromium.launch(headless=True)
    page = await browser_instance.new_page()

    try:
        await page.set_content("""
            <html>
                <body>
                    <button id="counter" onclick="window.count = (window.count || 0) + 1">Increment</button>
                </body>
            </html>
        """)

        executor = ActionExecutor(page)
        raw_action = {"type": "click", "target": {"css": "#counter"}}

        start_time = time.monotonic()
        res = await executor.execute(raw_action)
        elapsed = time.monotonic() - start_time

        assert res.get("success") is True
        assert res["result"].get("clicked") is True
        assert res["result"].get("navigation") is False
        count = await page.evaluate("window.count")
        assert count == 1
        # Before our fix, this took >= 5.0 seconds. Now it must complete in < 1.5s
        assert elapsed < 1.5, f"Click took {elapsed:.2f}s; expected < 1.5s"

    finally:
        await browser_instance.close()
        await pw.stop()
