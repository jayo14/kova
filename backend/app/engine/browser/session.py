"""Unified browser abstraction layer.

Provides a single BrowserSession class that wraps Playwright internally.
The execution engine depends only on this abstraction, not on Playwright directly.

Each execution gets its own isolated browser context.
Cleanup happens automatically on success, failure, cancellation, exception, or timeout.
"""

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

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

from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Serializable browser session state (cookies, localStorage, sessionStorage)."""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "session_storage": self.session_storage,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        return cls(
            cookies=data.get("cookies") or [],
            local_storage=data.get("local_storage") or {},
            session_storage=data.get("session_storage") or {},
            created_at=data.get("created_at") or time.time(),
        )


DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# SSRF protection: block private/internal IP ranges.
_CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")
_METADATA_HOSTS = {"metadata.google.internal", "169.254.169.254"}


def _redact_url(url: str) -> str:
    """Remove URL credentials and query values before storing diagnostic URLs."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunparse((parsed.scheme, host, parsed.path, parsed.params, "", ""))
    except Exception:
        return "[redacted URL]"


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
    if parsed.username is not None or parsed.password is not None:
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
        self.network_errors: list[dict[str, Any]] = []
        self.current_step_index: int = 0
        self.on_network_error: Callable[[dict[str, Any]], Any] | None = None

    async def start(self):
        """Launch browser and create isolated context + page."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            viewport=DEFAULT_VIEWPORT,
            user_agent=DEFAULT_USER_AGENT,
            service_workers="block",
        )
        self._page = await self._context.new_page()

        # Check every browser request, including subresources and redirects.
        # Context routing also applies to popups and newly-created pages.
        async def _intercept_request(route):
            req = route.request
            if req.url.startswith(("about:", "data:", "blob:")):
                await route.continue_()
                return
            if not _is_safe_url(req.url):
                logger.warning("SSRF: Aborting browser request to unsafe destination")
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await self._context.route("**/*", _intercept_request)

        # WebSockets do not pass through ordinary request routing. Reject
        # private destinations there as well (Playwright >= 1.48).
        if hasattr(self._context, "route_web_socket"):
            async def _intercept_websocket(ws_route):
                if not _is_safe_url(ws_route.url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)):
                    logger.warning("SSRF: Aborting WebSocket to unsafe URL")
                    await ws_route.close(code=1008, reason="Destination blocked")
                    return
                await ws_route.connect()

            await self._context.route_web_socket("**/*", _intercept_websocket)

        # Record same-origin responses >= 400, request failures, and page errors
        async def _on_response(response):
            try:
                if response.status >= 400:
                    page_url = self._page.url if self._page else ""
                    page_parsed = urlparse(page_url)
                    resp_parsed = urlparse(response.url)
                    is_same_origin = (
                        (page_parsed.netloc and resp_parsed.netloc == page_parsed.netloc)
                        or (page_parsed.hostname and resp_parsed.hostname == page_parsed.hostname)
                    )
                    if is_same_origin:
                        req = response.request
                        err_entry = {
                            "type": "http_error",
                            "status": response.status,
                            "method": req.method if req else "GET",
                            "url": _redact_url(response.url),
                            "path": resp_parsed.path or "/",
                            "step_index": self.current_step_index,
                        }
                        self.network_errors.append(err_entry)
                        if self.on_network_error:
                            res = self.on_network_error(err_entry)
                            if asyncio.iscoroutine(res):
                                asyncio.create_task(res)
            except Exception as e:
                logger.debug("Error in response listener: %s", e)

        async def _on_request_failed(request):
            try:
                page_url = self._page.url if self._page else ""
                page_parsed = urlparse(page_url)
                req_parsed = urlparse(request.url)
                is_same_origin = (
                    (page_parsed.netloc and req_parsed.netloc == page_parsed.netloc)
                    or (page_parsed.hostname and req_parsed.hostname == page_parsed.hostname)
                )
                if is_same_origin:
                    err_entry = {
                        "type": "request_failed",
                        "status": 0,
                        "method": request.method,
                        "url": _redact_url(request.url),
                        "path": req_parsed.path or "/",
                        "failure": request.failure or "Request failed",
                        "step_index": self.current_step_index,
                    }
                    self.network_errors.append(err_entry)
                    if self.on_network_error:
                        res = self.on_network_error(err_entry)
                        if asyncio.iscoroutine(res):
                            asyncio.create_task(res)
            except Exception as e:
                logger.debug("Error in requestfailed listener: %s", e)

        async def _on_page_error(error):
            try:
                err_entry = {
                    "type": "page_error",
                    "status": 0,
                    "method": "PAGE",
                    "url": self._page.url if self._page else "",
                    "path": urlparse(self._page.url if self._page else "").path or "/",
                    "failure": str(error),
                    "step_index": self.current_step_index,
                }
                self.network_errors.append(err_entry)
                if self.on_network_error:
                    res = self.on_network_error(err_entry)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
            except Exception as e:
                logger.debug("Error in pageerror listener: %s", e)

        self._page.on("response", _on_response)
        self._page.on("requestfailed", _on_request_failed)
        self._page.on("pageerror", _on_page_error)

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
            raise ValueError("Blocked navigation to unsafe URL")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Redirect chain may land on blocked host — re-check final URL
        final_url = self.page.url or ""
        if final_url and not _is_safe_url(final_url):
            # Navigate away to blank to leave a safe state
            try:
                await self.page.goto("about:blank", wait_until="commit", timeout=5000)
            except Exception:
                pass
            raise ValueError("Blocked post-redirect navigation to unsafe URL")
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

    async def fill(self, selector: str, value: str):
        """Fill an input element by selector."""
        await self.page.fill(selector, value)

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
    # --- Session State Persistence ---

    async def save_session_state(self) -> "SessionState":
        """Capture cookies, localStorage, and sessionStorage from the current browser session."""
        cookies = []
        if self.context:
            try:
                cookies = await self.context.cookies()
            except Exception as e:
                logger.debug("Failed to extract cookies: %s", e)

        local_storage: dict[str, str] = {}
        session_storage: dict[str, str] = {}
        if self.page and not self.page.is_closed():
            try:
                local_storage = await self.page.evaluate("() => Object.assign({}, window.localStorage)")
            except Exception as e:
                logger.debug("Failed to extract localStorage: %s", e)
            try:
                session_storage = await self.page.evaluate("() => Object.assign({}, window.sessionStorage)")
            except Exception as e:
                logger.debug("Failed to extract sessionStorage: %s", e)

        return SessionState(
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
            created_at=time.time(),
        )

    async def restore_session_state(self, state: "SessionState") -> None:
        """Restore cookies, localStorage, and sessionStorage into the current browser session."""
        if not state:
            return
        if self.context and state.cookies:
            try:
                await self.context.add_cookies(state.cookies)
            except Exception as e:
                logger.warning("Failed to restore cookies: %s", e)

        if self.page and not self.page.is_closed():
            if state.local_storage:
                try:
                    await self.page.evaluate(
                        """(entries) => {
                            for (const [k, v] of Object.entries(entries)) {
                                window.localStorage.setItem(k, v);
                            }
                        }""",
                        state.local_storage,
                    )
                except Exception as e:
                    logger.debug("Failed to restore localStorage: %s", e)
            if state.session_storage:
                try:
                    await self.page.evaluate(
                        """(entries) => {
                            for (const [k, v] of Object.entries(entries)) {
                                window.sessionStorage.setItem(k, v);
                            }
                        }""",
                        state.session_storage,
                    )
                except Exception as e:
                    logger.debug("Failed to restore sessionStorage: %s", e)

    # --- Context manager ---

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False
