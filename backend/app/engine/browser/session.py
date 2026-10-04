"""Unified browser abstraction layer.

Provides a single BrowserSession class that wraps Playwright internally.
The execution engine depends only on this abstraction, not on Playwright directly.

Each execution gets its own isolated browser context.
Cleanup happens automatically on success, failure, cancellation, exception, or timeout.
"""

import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.config.settings import settings
from app.engine.browser.observer import PageObserver
from app.engine.browser.resolver import ResolutionStrategy, TargetResolver
from app.engine.browser.executor import ActionExecutor

logger = logging.getLogger(__name__)

DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# SSRF protection: block private/internal IP ranges.
_CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")
_METADATA_HOSTS = {"metadata.google.internal", "169.254.169.254"}


def _parse_raw_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse raw IP in standard, decimal integer, hex, or dotted-hex/octal forms."""
    h = host.strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass

    # Decimal integer IP (e.g. 2130706433)
    if h.isdigit():
        try:
            val = int(h)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    # Hex IP (e.g. 0x7f000001)
    if h.lower().startswith("0x"):
        try:
            val = int(h, 16)
            if 0 <= val <= 0xFFFFFFFF:
                return ipaddress.IPv4Address(val)
        except ValueError:
            pass

    # Dotted hex/octal (e.g. 0x7f.0.0.1)
    parts = h.split(".")
    if len(parts) == 4:
        try:
            nums = [int(p, 0) for p in parts]
            if all(0 <= n <= 255 for n in nums):
                return ipaddress.IPv4Address(bytes(nums))
        except (ValueError, OverflowError):
            pass

    return None


def _is_ip_safe(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, allow_loopback: bool) -> bool:
    """Check if resolved IP is safe from SSRF."""
    # Unmap IPv6-mapped IPv4 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if ip.is_loopback:
        return allow_loopback
    if (
        ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or ip in _CARRIER_GRADE_NAT
    ):
        return False

    return True


def _is_safe_url(url: str, *, allow_loopback: bool | None = None) -> bool:
    """Check if a URL is safe to navigate to (SSRF protection).

    Resolves hostname with socket.getaddrinfo and rejects any address that is
    private, loopback, link-local, reserved, multicast, or in 100.64.0.0/10.
    Handles decimal, hex, and IPv6-mapped forms.
    """
    if allow_loopback is None:
        allow_loopback = not settings.is_production

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname or ""
    if not hostname:
        return False

    host = hostname.lower()
    if host in _METADATA_HOSTS:
        return False

    # Check for direct raw IP representations first (decimal, hex, etc.)
    raw_ip = _parse_raw_ip(host)
    if raw_ip is not None:
        return _is_ip_safe(raw_ip, allow_loopback)

    # For literal localhost:
    if host == "localhost":
        return allow_loopback

    # Resolve hostname with socket.getaddrinfo
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    except Exception:
        return False

    if not addr_info:
        return False

    # Reject if any resolved IP address is unsafe
    for info in addr_info:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        is_loopback_host = host in ("localhost", "127.0.0.1", "::1")
        effective_allow_loopback = allow_loopback and is_loopback_host

        if not _is_ip_safe(ip, effective_allow_loopback):
            return False

    return True


class BrowserSession:
    """Unified browser session wrapping Playwright Chromium.

    Lifecycle:
        1. start() - launches browser and creates isolated context
        2. navigate/click/type/... - perform actions
        3. close() - cleans up context, browser, and playwright

    Usage as async context manager (preferred):
        async with BrowserSession() as browser:
            await browser.navigate("http://example.com")
            await browser.click("#submit")

    Usage manually:
        browser = BrowserSession()
        await browser.start()
        try:
            await browser.navigate("http://example.com")
        finally:
            await browser.close()
    """

    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self):
        """Launch browser and create isolated context + page."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            user_agent=DEFAULT_USER_AGENT,
        )
        self._page = await self._context.new_page()

        # Re-check every document navigation and redirect through page.route
        async def _intercept_navigation(route):
            req = route.request
            if req.is_navigation_request() or req.resource_type == "document":
                if not _is_safe_url(req.url):
                    logger.warning("SSRF: Aborting route navigation/redirect to unsafe URL: %s", req.url)
                    await route.abort("blockedbyclient")
                    return
            await route.continue_()

        await self._page.route("**/*", _intercept_navigation)
        logger.info("Browser session started")

    async def close(self):
        """Clean up all resources in reverse order.

        Safe to call multiple times. Handles partial initialization.
        """
        try:
            if self._context:
                await self._context.close()
                self._context = None
        except Exception as e:
            logger.warning("Error closing context: %s", e)

        try:
            if self._browser:
                await self._browser.close()
                self._browser = None
        except Exception as e:
            logger.warning("Error closing browser: %s", e)

        try:
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.warning("Error stopping playwright: %s", e)

        self._page = None
        logger.info("Browser session closed")

    @property
    def page(self) -> Page:
        """Get the current page. Raises if session not started."""
        if self._page is None:
            raise RuntimeError("Browser session not started or already closed")
        return self._page

    @property
    def is_started(self) -> bool:
        """Check if the browser session is active."""
        return self._page is not None

    # --- Navigation ---

    async def navigate(self, url: str):
        """Navigate to a URL and wait for DOM content to load.

        SSRF: checks both the target URL and the final post-redirect URL.
        """
        if not _is_safe_url(url):
            raise ValueError(f"Blocked navigation to unsafe URL: {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Redirect chain may land on blocked host — re-check final URL
        final_url = self.page.url or ""
        if final_url and not _is_safe_url(final_url):
            # Navigate away to blank to leave a safe state
            try:
                await self.page.goto("about:blank", wait_until="commit", timeout=5000)
            except Exception:
                pass
            raise ValueError(f"Blocked post-redirect navigation to unsafe URL: {final_url}")
        logger.debug("Navigated to %s", final_url or url)

    async def go_back(self):
        """Navigate back in browser history."""
        await self.page.go_back(wait_until="domcontentloaded", timeout=45000)
        logger.debug("Navigated back to %s", self.page.url)

    async def go_forward(self):
        """Navigate forward in browser history."""
        await self.page.go_forward(wait_until="domcontentloaded", timeout=45000)
        logger.debug("Navigated forward to %s", self.page.url)

    async def reload(self):
        """Reload the current page."""
        await self.page.reload(wait_until="domcontentloaded", timeout=45000)
        logger.debug("Reloaded page at %s", self.page.url)

    # --- Interaction actions ---

    async def click(self, target: str, *, role: str = "", strategy: ResolutionStrategy | None = None):
        """Click an element resolved by the target resolver.

        Falls back to CSS selector if resolver finds no match.
        """
        resolver = TargetResolver(self.page)
        try:
            locator = await resolver.resolve(target, role=role, strategy=strategy)
            await locator.click()
        except Exception:
            # Fallback to raw CSS
            await self.page.click(target)
        logger.debug("Clicked %s", target)

    async def type(self, target: str, value: str, *, role: str = "", strategy: ResolutionStrategy | None = None):
        """Type text into an element resolved by the target resolver."""
        resolver = TargetResolver(self.page)
        try:
            locator = await resolver.resolve(target, role=role, strategy=strategy)
            await locator.fill(value)
        except Exception:
            await self.page.fill(target, value)
        logger.debug("Typed into %s", target)

    async def clear(self, target: str, *, role: str = "", strategy: ResolutionStrategy | None = None):
        """Clear the content of an input element."""
        resolver = TargetResolver(self.page)
        try:
            locator = await resolver.resolve(target, role=role, strategy=strategy)
            await locator.fill("")
        except Exception:
            await self.page.fill(target, "")
        logger.debug("Cleared %s", target)

    async def press(self, key: str):
        """Press a keyboard key (e.g. 'Enter', 'Tab', 'Escape')."""
        await self.page.keyboard.press(key)
        logger.debug("Pressed key %s", key)

    async def scroll(self, direction: str = "down", amount: int = 500):
        """Scroll the page by a given amount in a direction.

        Args:
            direction: 'up' or 'down'
            amount: pixels to scroll
        """
        delta = amount if direction == "down" else -amount
        await self.page.mouse.wheel(0, delta)
        logger.debug("Scrolled %s by %dpx", direction, amount)

    async def screenshot(self) -> bytes:
        """Take a screenshot of the current page. Returns PNG bytes."""
        return await self.page.screenshot()

    # --- Observation ---

    async def observe(self) -> dict[str, Any]:
        """Observe the current page state using PageObserver.

        Returns structured data with url, title, elements, forms, and text.
        """
        observer = PageObserver(self.page)
        return await observer.observe()

    # --- Structured action execution ---

    async def execute_action(
        self,
        raw_action: dict,
        execution_id=None,
        event_recorder=None,
    ) -> dict[str, Any]:
        """Execute a structured action using ActionExecutor.

        Args:
            raw_action: Action dict with 'type', 'target', 'value', etc.
            execution_id: Optional UUID for event recording.
            event_recorder: Optional callable for emitting events.

        Returns:
            {"success": True, "action": {...}, "result": {...}}
            or {"success": False, "error": {...}}
        """
        executor = ActionExecutor(self.page, event_recorder)
        return await executor.execute(raw_action, execution_id)

    # --- Context manager ---

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
