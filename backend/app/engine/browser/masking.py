"""Shared sensitive-field masking for screenshots.

Single source of truth for what is considered a sensitive input. Used by:
  - BrowserSession.capture_step_screenshot (stored evidence)
  - FlowRunner live-frame producers (_frame_producer, _capture_live_snapshot)

Honesty contract: a live frame is either captured WITH the mask applied, or it
is not published at all. A frame of a page containing a password/OTP/token
input is never sent without the mask.
"""

import logging
import re
from typing import Any

from app.config.settings import settings

logger = logging.getLogger(__name__)

SENSITIVE_MASK_SELECTOR = (
    'input[type="password"], '
    'input[name*="password" i], '
    'input[autocomplete*="password" i], '
    'input[name*="otp" i], '
    'input[name*="token" i], '
    'input[name*="secret" i], '
    'input[data-testid*="otp" i], '
    'input[data-testid*="password" i]'
)


def validate_sensitive_selector(selector: str) -> bool:
    """Guard against unsafe selectors coming from configuration."""
    if not isinstance(selector, str) or not selector.strip():
        return False
    if len(selector) > 250:
        return False
    if re.search(r"<|javascript:|;|\{|\}", selector):
        return False
    return True


def build_sensitive_mask_selector(extra_selectors: list[str] | None = None) -> str:
    """Compose the configured sensitive selector including env extras."""
    parts = [SENSITIVE_MASK_SELECTOR]
    for raw in extra_selectors or []:
        sel = (raw or "").strip()
        if not validate_sensitive_selector(sel):
            logger.debug("Ignoring invalid live-frame mask selector %r", raw)
            continue
        parts.append(sel)
    return ", ".join(parts)


def build_mask_locators(page: Any, extra_selectors: list[str] | None = None) -> list[Any]:
    """Build Playwright mask locators for the shared selector. Never raises."""
    try:
        selector = build_sensitive_mask_selector(extra_selectors)
        return [page.locator(selector)]
    except Exception:
        return []


def configured_extra_mask_selectors() -> list[str]:
    """Additional sensitive selectors configured via settings (comma-separated)."""
    raw = getattr(settings, "LIVE_FRAME_EXTRA_SENSITIVE_SELECTORS", "") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


def mask_capture_failed(page: Any) -> bool:
    """True when we cannot know masked capture is possible (no/closed page)."""
    if page is None:
        return True
    try:
        is_closed = page.is_closed
        if callable(is_closed):
            return bool(is_closed())
        return bool(is_closed)
    except Exception:
        return True


async def capture_masked_live_frame(page: Any) -> tuple[str, bytes]:
    """Capture a JPEG live frame with the sensitive mask applied.

    Returns ("masked", jpeg_bytes) or ("blocked", b"").
    On any capture failure the caller must NOT publish an unmasked frame —
    this is what guarantees a raw password/OTP value never reaches a viewer.
    """
    if mask_capture_failed(page):
        return ("blocked", b"")
    locators = build_mask_locators(page, configured_extra_mask_selectors())
    try:
        jpeg = await page.screenshot(
            type="jpeg",
            quality=45,
            timeout=2000,
            animations="disabled",
            caret="hide",
            mask=locators,
        )
    except Exception as e:
        logger.debug("Masked live-frame capture failed (frame withheld): %s", e)
        return ("blocked", b"")
    if not jpeg:
        return ("blocked", b"")
    return ("masked", jpeg)
