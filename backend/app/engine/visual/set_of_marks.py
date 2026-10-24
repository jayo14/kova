"""Set-of-Marks (SoM) visual grounding for browser sessions.

Injects non-destructive numbered badge overlays over ranked interactive elements,
captures a screenshot, and cleans up the DOM overlay immediately.
"""

from __future__ import annotations

import logging
from typing import Any

from app.engine.browser.session import BrowserSession

logger = logging.getLogger(__name__)

SOM_INJECT_SCRIPT = """
(marks) => {
    const prev = document.getElementById('kova-som-container');
    if (prev) prev.remove();
    const container = document.createElement('div');
    container.id = 'kova-som-container';
    container.style.position = 'fixed';
    container.style.top = '0';
    container.style.left = '0';
    container.style.width = '100vw';
    container.style.height = '100vh';
    container.style.pointerEvents = 'none';
    container.style.zIndex = '2147483647';

    marks.forEach(m => {
        const box = document.createElement('div');
        box.style.position = 'absolute';
        box.style.left = m.x + 'px';
        box.style.top = m.y + 'px';
        box.style.width = m.width + 'px';
        box.style.height = m.height + 'px';
        box.style.border = '2px solid #ef4444';
        box.style.boxSizing = 'border-box';
        box.style.pointerEvents = 'none';
        container.appendChild(box);

        const badge = document.createElement('div');
        badge.innerText = String(m.index);
        badge.style.position = 'absolute';
        badge.style.left = Math.max(0, m.x - 2) + 'px';
        badge.style.top = Math.max(0, m.y - 14) + 'px';
        badge.style.backgroundColor = '#ef4444';
        badge.style.color = '#ffffff';
        badge.style.fontSize = '11px';
        badge.style.fontWeight = 'bold';
        badge.style.padding = '0px 4px';
        badge.style.borderRadius = '2px';
        badge.style.zIndex = '2147483647';
        badge.style.pointerEvents = 'none';
        badge.style.boxShadow = '0 1px 2px rgba(0,0,0,0.5)';
        container.appendChild(badge);
    });

    document.body.appendChild(container);
}
"""

SOM_CLEANUP_SCRIPT = """
() => {
    const el = document.getElementById('kova-som-container');
    if (el) el.remove();
}
"""


async def capture_set_of_marks(
    browser: BrowserSession,
    elements: list[dict[str, Any]],
    max_marks: int = 30,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Inject numbered marks on elements, capture screenshot, and remove marks cleanly."""
    if not browser or not browser.page:
        return b"", []

    # Filter elements with positive bounding boxes visible in the viewport
    valid_elements: list[dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        box = el.get("bounding_box") or {}
        if not isinstance(box, dict):
            continue
        w = box.get("width", 0)
        h = box.get("height", 0)
        x = box.get("x", 0)
        y = box.get("y", 0)
        if w > 4 and h > 4 and x >= -10 and y >= -10:
            valid_elements.append(el)

    marks: list[dict[str, Any]] = []
    for i, el in enumerate(valid_elements[:max_marks], start=1):
        box = el.get("bounding_box", {})
        marks.append({
            "index": i,
            "x": int(box.get("x", 0)),
            "y": int(box.get("y", 0)),
            "width": int(box.get("width", 0)),
            "height": int(box.get("height", 0)),
            "type": el.get("type", "element"),
            "role": el.get("role", ""),
            "name": el.get("accessible_name") or el.get("name") or el.get("selector", ""),
            "selector": el.get("selector", ""),
            "frame": el.get("frame", "main"),
            "element": el,
        })

    if not marks:
        return b"", []

    try:
        # Transfer mark positions to JS evaluation
        js_payload = [
            {"index": m["index"], "x": m["x"], "y": m["y"], "width": m["width"], "height": m["height"]}
            for m in marks
        ]
        await browser.page.evaluate(SOM_INJECT_SCRIPT, js_payload)
        screenshot_bytes = await browser.screenshot(full_page=False)
        return screenshot_bytes, marks
    except Exception as e:
        logger.warning("Failed to capture set-of-marks screenshot: %s", e)
        return b"", marks
    finally:
        try:
            await browser.page.evaluate(SOM_CLEANUP_SCRIPT)
        except Exception:
            pass
