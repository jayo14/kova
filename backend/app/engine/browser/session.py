"""Unified browser abstraction layer.

Provides a single BrowserSession class that wraps Playwright internally.
The execution engine depends only on this abstraction, not on Playwright directly.

Each execution gets its own isolated browser context.
Cleanup happens automatically on success, failure, cancellation, exception, or timeout.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.config.settings import settings
from app.engine.browser.egress import _is_safe_url, _redact_url, evaluate_url
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

BLOCKED_DOWNLOAD_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif", ".dll", ".sys",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".sh", ".bash", ".zsh", ".jar", ".app", ".deb", ".rpm", ".dmg",
    ".pkg", ".lnk", ".hta", ".cpl",
}


def _sanitize_filename(name: str) -> str:
    name = re.sub(r"[\x00-\x1f]", "", name).replace("\\", "/")
    name = name.rsplit("/", 1)[-1].strip()
    if name in ("", ".", ".."):
        return "download.bin"
    return name[:200]


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

    def __init__(self, headless: bool = True, browser_settings: Any = None, job_id: str | None = None):
        self._headless = headless
        self._browser_settings = browser_settings
        self.job_id = job_id
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.network_errors: list[dict[str, Any]] = []
        self.console_errors: list[dict[str, Any]] = []
        self.failed_requests: list[dict[str, Any]] = []
        self.download_events: list[dict[str, Any]] = []
        self.current_step_index: int = 0
        self.on_network_error: Callable[[dict[str, Any]], Any] | None = None
        self.video_path: str | None = None
        self.trace_path: str | None = None
        self._step_network_logs: list[dict[str, Any]] = []
        self._capturing_step_network: bool = False

    async def start(self):
        """Launch browser and create isolated context + page.

        Idempotent: if the session is already started, the current context
        is replaced with a fresh one instead of leaking a second browser
        launch. Every job therefore begins with a clean context.
        """
        if self.is_started:
            await self.fresh_context()
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        await self._setup_context()
        logger.info("Browser session started")

    async def fresh_context(self):
        """Replace the current context with a brand-new isolated one.

        Keeps the browser process but drops every cookie, storage entry,
        page, and listener from the previous context. Requires a started
        session (see start()).
        """
        if self._browser is None:
            raise RuntimeError("Browser session not started")
        old_context = self._context
        self._context = None
        self._page = None
        self.network_errors = []
        self.console_errors = []
        self.failed_requests = []
        self.download_events = []
        if old_context is not None:
            try:
                await old_context.close()
            except Exception as e:
                logger.debug("Failed to close old context: %s", e)
        await self._setup_context()

    async def _on_download(self, download) -> None:
        """Persist an untrusted page download into the job-scoped directory.

        Rejects executable/script types and enforces per-job file-count and
        byte-size limits. Every outcome is recorded on self.download_events.
        """
        suggested = download.suggested_filename or "download.bin"
        filename = _sanitize_filename(suggested)
        event: dict[str, Any] = {"filename": filename, "url": download.url}
        try:
            job_dir = Path(settings.BROWSER_DOWNLOAD_DIR) / (self.job_id or "unscoped")
            job_dir.mkdir(parents=True, exist_ok=True)
            existing = sum(1 for p in job_dir.iterdir() if p.is_file())
            suffix = Path(filename).suffix.lower()
            if suffix in BLOCKED_DOWNLOAD_EXTENSIONS:
                await download.cancel()
                event["status"] = "rejected_type"
                logger.warning(
                    "Blocked download type %s (%s)",
                    suffix,
                    _redact_url(download.url),
                )
            elif existing >= settings.BROWSER_DOWNLOAD_MAX_FILES:
                await download.cancel()
                event["status"] = "rejected_file_limit"
                logger.warning(
                    "Rejected download beyond job file limit: %s", filename
                )
            else:
                dest = job_dir / filename
                await download.save_as(dest)
                size = dest.stat().st_size
                if size > settings.BROWSER_DOWNLOAD_MAX_BYTES:
                    dest.unlink(missing_ok=True)
                    event["status"] = "rejected_too_large"
                    event["size"] = size
                    logger.warning(
                        "Rejected oversized download %s (%d bytes)", filename, size
                    )
                else:
                    event["status"] = "saved"
                    event["size"] = size
                    event["path"] = str(dest)
                    logger.info("Saved job download %s (%d bytes)", filename, size)
        except Exception as e:
            event["status"] = "error"
            event["error"] = str(e)
            logger.warning(
                "Download handling failed (%s): %s", _redact_url(download.url), e
            )
        self.download_events.append(event)

    async def _setup_context(self):
        """Create context + page with interception, tracing, and observers."""
        import os
        viewport = DEFAULT_VIEWPORT
        user_agent = DEFAULT_USER_AGENT
        locale = None
        timezone_id = None
        if self._browser_settings:
            bs = self._browser_settings
            if hasattr(bs, "viewport_width") and hasattr(bs, "viewport_height"):
                viewport = {"width": bs.viewport_width, "height": bs.viewport_height}
            elif isinstance(bs, dict) and "viewport_width" in bs and "viewport_height" in bs:
                viewport = {"width": bs["viewport_width"], "height": bs["viewport_height"]}

            if hasattr(bs, "user_agent_override") and bs.user_agent_override:
                user_agent = bs.user_agent_override
            elif isinstance(bs, dict) and bs.get("user_agent_override"):
                user_agent = bs["user_agent_override"]

            if hasattr(bs, "locale") and bs.locale:
                locale = bs.locale
            elif isinstance(bs, dict) and bs.get("locale"):
                locale = bs["locale"]

            if hasattr(bs, "timezone") and bs.timezone:
                timezone_id = bs.timezone
            elif isinstance(bs, dict) and bs.get("timezone"):
                timezone_id = bs["timezone"]

        context_kwargs: dict[str, Any] = {
            "viewport": viewport,
            "user_agent": user_agent,
            "service_workers": "block",
            "permissions": [],
            "accept_downloads": True,
        }
        if locale:
            context_kwargs["locale"] = locale
        if timezone_id:
            context_kwargs["timezone_id"] = timezone_id
        if getattr(settings, "EVIDENCE_CAPTURE_VIDEO", False):
            video_dir = getattr(settings, "EVIDENCE_VIDEO_DIR", "/tmp/kova_videos")
            os.makedirs(video_dir, exist_ok=True)
            context_kwargs["record_video_dir"] = video_dir
            context_kwargs["record_video_size"] = {"width": 1280, "height": 720}

        self._context = await self._browser.new_context(**context_kwargs)
        try:
            await self._context.tracing.start(screenshots=True, snapshots=True, sources=False)
        except Exception as e:
            logger.debug("Failed to start tracing: %s", e)

        self._page = await self._context.new_page()

        # Check every browser request, including subresources and redirects.
        # Context routing also applies to popups and newly-created pages.
        async def _intercept_request(route):
            req = route.request
            if req.url.startswith(("about:", "data:", "blob:")):
                await route.continue_()
                return
            verdict = evaluate_url(req.url)
            if not verdict.safe:
                logger.warning("SSRF: Aborting browser request to unsafe destination")
                await route.abort("blockedbyclient")
                return
            if verdict.pin_url and verdict.host_header:
                # DNS rebinding defense: connect to the address we just
                # verified instead of letting Chromium resolve again.
                # Host header keeps the original vhost routing intact.
                headers = dict(req.headers)
                headers["host"] = verdict.host_header
                try:
                    await route.continue_(url=verdict.pin_url, headers=headers)
                    return
                except Exception as e:
                    logger.warning(
                        "SSRF pin rejected for %s (%s); continuing unpinned",
                        _redact_url(verdict.pin_url),
                        e,
                    )
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
                if self._capturing_step_network:
                    req = response.request
                    try:
                        req_headers = dict(req.headers) if req and hasattr(req, "headers") else {}
                        resp_headers = dict(response.headers) if hasattr(response, "headers") else {}
                        safe_req_headers = {
                            k: ("[REDACTED]" if k.lower() in ("authorization", "cookie", "proxy-authorization", "x-api-key") else v)
                            for k, v in req_headers.items()
                        }
                        safe_resp_headers = {
                            k: ("[REDACTED]" if k.lower() in ("set-cookie",) else v)
                            for k, v in resp_headers.items()
                        }
                        self._step_network_logs.append({
                            "url": _redact_url(response.url),
                            "method": req.method if req else "GET",
                            "status": response.status,
                            "status_text": response.status_text if hasattr(response, "status_text") else "",
                            "request_headers": safe_req_headers,
                            "response_headers": safe_resp_headers,
                        })
                    except Exception as ex:
                        logger.debug("Error recording step network log: %s", ex)

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
                err_entry = {
                    "type": "request_failed",
                    "status": 0,
                    "method": request.method,
                    "url": _redact_url(request.url),
                    "path": req_parsed.path or "/",
                    "failure": request.failure or "Request failed",
                    "step_index": self.current_step_index,
                    "timestamp": time.time(),
                }
                self.failed_requests.append(err_entry)
                is_same_origin = (
                    (page_parsed.netloc and req_parsed.netloc == page_parsed.netloc)
                    or (page_parsed.hostname and req_parsed.hostname == page_parsed.hostname)
                )
                if is_same_origin:
                    self.network_errors.append(err_entry)
                    if self.on_network_error:
                        res = self.on_network_error(err_entry)
                        if asyncio.iscoroutine(res):
                            asyncio.create_task(res)
            except Exception as e:
                logger.debug("Error in requestfailed listener: %s", e)

        async def _on_console(msg):
            try:
                if msg.type in ("error", "warning"):
                    self.console_errors.append({
                        "type": msg.type,
                        "text": msg.text,
                        "location": getattr(msg, "location", None),
                        "step_index": self.current_step_index,
                        "timestamp": time.time(),
                    })
            except Exception as e:
                logger.debug("Error in console listener: %s", e)

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
        self._page.on("console", _on_console)
        self._page.on("pageerror", _on_page_error)

        logger.info("Browser context ready (job=%s)", self.job_id)

    async def close(self):
        """Clean up all resources in reverse order.

        Safe to call multiple times. Handles partial initialization.
        """
        import os
        import uuid

        if self._page and hasattr(self._page, "video") and self._page.video:
            try:
                self.video_path = await self._page.video.path()
            except Exception as e:
                logger.debug("Failed to get video path: %s", e)

        if self._context:
            try:
                trace_dir = getattr(settings, "EVIDENCE_VIDEO_DIR", "/tmp/kova_traces")
                os.makedirs(trace_dir, exist_ok=True)
                trace_file = os.path.join(trace_dir, f"trace_{uuid.uuid4().hex}.zip")
                await self._context.tracing.stop(path=trace_file)
                self.trace_path = trace_file
            except Exception as e:
                logger.debug("Failed to stop tracing: %s", e)

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
    def context(self) -> BrowserContext | None:
        """Get the current browser context."""
        return self._context

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

    async def click(self, target: str, *, role: str = "", strategy: ResolutionStrategy | None = None, objective: str | None = None):
        """Click an element resolved by the target resolver.

        Resolution ladder: DOM strategies (test id → role+name → label → text → CSS),
        then a visual fallback (screenshot + VLM + hit test) when the DOM yields no
        reliable match. Falls back to raw CSS only as a last resort.
        """
        resolver = TargetResolver(self.page)
        try:
            locator = await resolver.resolve(target, role=role, strategy=strategy)
            await locator.click()
            logger.debug("Clicked %s via %s", target, resolver.last_resolution_strategy)
            return
        except Exception:
            pass
        # Visual fallback: propose coordinates by screenshot+VLM, hit-test validate.
        if objective:
            try:
                coords = await resolver.resolve_visual(objective)
                if coords:
                    x, y = coords
                    await self.page.mouse.click(x, y)
                    logger.debug("Clicked visual target at (%d, %d) for %s", x, y, objective[:60])
                    return
            except Exception:
                pass
        # Last resort: raw CSS click.
        try:
            await self.page.click(target)
        except Exception:
            logger.debug("Click failed for %s", target)

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

    async def screenshot(self, full_page: bool = False) -> bytes:
        """Take a screenshot of the current page. Returns PNG bytes."""
        return await self.page.screenshot(full_page=full_page)

    async def capture_step_screenshot(
        self,
        step_id: str,
        kind: str = "after",
        target_locator: Any | None = None,
        timeout_ms: int = 3000,
    ) -> tuple[bytes, str, str]:
        """Capture screenshot with animations disabled, caret hidden, masked inputs, and fallback chain (§Prompt D).

        Returns: (image_bytes, mime_type, fallback_level)
        Fallback chain:
        1. Full page screenshot with sensitive inputs masked
        2. Viewport screenshot (full_page=False)
        3. Element screenshot (if locator provided)
        4. DOM snapshot fallback
        """
        if not self._page:
            return (b"", "image/png", "no_page")

        mask_locators = []
        try:
            mask_locators = [
                self._page.locator(
                    'input[type="password"], '
                    'input[name*="password" i], '
                    'input[autocomplete*="password" i], '
                    'input[name*="otp" i], '
                    'input[name*="token" i], '
                    'input[name*="secret" i], '
                    'input[data-testid*="otp" i], '
                    'input[data-testid*="password" i]'
                )
            ]
        except Exception:
            mask_locators = []

        # 1. Full page screenshot
        try:
            bytes_data = await self.page.screenshot(
                full_page=True,
                animations="disabled",
                caret="hide",
                timeout=timeout_ms,
                mask=mask_locators,
            )
            if bytes_data:
                return (bytes_data, "image/png", "full_page")
        except Exception as e1:
            logger.debug("Full page screenshot fallback for %s (%s): %s", step_id, kind, e1)

        # 2. Viewport screenshot
        try:
            bytes_data = await self.page.screenshot(
                full_page=False,
                animations="disabled",
                caret="hide",
                timeout=min(2000, timeout_ms),
                mask=mask_locators,
            )
            if bytes_data:
                return (bytes_data, "image/png", "viewport")
        except Exception as e2:
            logger.debug("Viewport screenshot fallback for %s (%s): %s", step_id, kind, e2)

        # 3. Element screenshot if locator provided
        if target_locator is not None:
            try:
                if hasattr(target_locator, "screenshot"):
                    bytes_data = await target_locator.screenshot(timeout=1500)
                    if bytes_data:
                        return (bytes_data, "image/png", "element")
                elif isinstance(target_locator, str) and self._page:
                    bytes_data = await self._page.locator(target_locator).screenshot(timeout=1500)
                    if bytes_data:
                        return (bytes_data, "image/png", "element")
            except Exception as e3:
                logger.debug("Element screenshot fallback for %s (%s): %s", step_id, kind, e3)

        # 4. DOM snapshot fallback (1x1 transparent PNG)
        FALLBACK_PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82'
        return (FALLBACK_PNG, "image/png", "dom_snapshot")

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
        return await executor.execute(raw_action, execution_id=execution_id)

    # --- Evidence Capture Helpers ---

    def start_step_network_capture(self) -> None:
        """Start capturing network requests/responses for the current step."""
        self._step_network_logs = []
        self._capturing_step_network = True

    def stop_step_network_capture(self) -> list[dict[str, Any]]:
        """Stop capturing network requests and return the list of recorded network logs."""
        self._capturing_step_network = False
        logs = list(self._step_network_logs)
        self._step_network_logs = []
        return logs

    async def get_dom_snapshot(self) -> str:
        """Capture the current page DOM HTML snapshot."""
        if not self._page or self._page.is_closed():
            return ""
        try:
            return await self._page.content()
        except Exception as e:
            logger.debug("Failed to capture DOM snapshot: %s", e)
            return ""

    async def get_a11y_tree(self) -> str:
        """Capture the current page accessibility tree as a serialized JSON string."""
        if not self._page or self._page.is_closed():
            return ""
        try:
            if hasattr(self._page, "accessibility") and hasattr(self._page.accessibility, "snapshot"):
                snap = await self._page.accessibility.snapshot()
                if snap is not None:
                    import json
                    return json.dumps(snap)
        except Exception as e:
            logger.debug("Failed to capture accessibility tree: %s", e)
        return ""

    async def get_element_screenshot(self, target: Any) -> bytes | None:
        """Capture a screenshot of a specific target element if resolvable."""
        if not self._page or self._page.is_closed():
            return None
        try:
            resolver = TargetResolver(self._page)
            loc = None
            if isinstance(target, dict):
                # Try CSS first, then test_id, label, text
                if target.get("css"):
                    loc = await resolver.resolve(target["css"], strategy=ResolutionStrategy.CSS)
                elif target.get("test_id"):
                    loc = await resolver.resolve(target["test_id"], strategy=ResolutionStrategy.TEST_ID)
                elif target.get("role") and target.get("name"):
                    loc = await resolver.resolve(target["name"], role=target["role"], strategy=ResolutionStrategy.ROLE_NAME)
                elif target.get("text"):
                    loc = await resolver.resolve(target["text"], strategy=ResolutionStrategy.TEXT)
            elif isinstance(target, str) and target.strip():
                loc = await resolver.resolve(target.strip())

            if loc:
                return await loc.screenshot()
        except Exception as e:
            logger.debug("Failed to capture element screenshot: %s", e)
        return None

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
