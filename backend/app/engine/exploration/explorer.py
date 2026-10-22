"""Autonomous exploration engine for target web applications.

Controls an isolated Playwright browser to:
1. Connect to and navigate target applications
2. Detect authentication barriers using combined signals
3. Authenticate with test credentials
4. Detect user roles and workspaces
5. Discover application workflows and user journeys
6. Synthesize candidate missions with verification criteria
"""

import asyncio
import inspect
import logging
import re
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

from app.engine.browser.session import BrowserSession
from app.engine.browser.screenshot_storage import screenshot_storage
from app.modules.exploration.models import ExplorationStatus
from app.modules.exploration.schemas import (
    AgentQuestion,
    AgentQuestionOption,
    CredentialRequest,
    DiscoveredMission,
    DiscoveryItem,
)
from app.engine.ai.provider import get_ai_provider
from app.engine.ai.reasoner import AgentReasoner

logger = logging.getLogger(__name__)

NAVIGATION_TIMEOUT_MS = 45000
ACTION_TIMEOUT_MS = 15000

# Patterns indicating an error/invalid page
ERROR_PAGE_PATTERNS = [
    r"\b404\b.*not found",
    r"\b403\b.*forbidden",
    r"\b401\b.*unauthorized",
    r"\b500\b.*internal server error",
    r"\b502\b.*bad gateway",
    r"\b503\b.*service unavailable",
    r"page you were looking for",
    r"this page could not be found",
    r"the page you are looking for",
    r"cannot get",
    r"application error",
    r"vercel.*not found",
    r"netlify.*not found",
    r"heroku.*no such app",
]

# Common error page title patterns
ERROR_TITLE_PATTERNS = [
    "404",
    "not found",
    "forbidden",
    "unauthorized",
    "error",
    "oops",
    "something went wrong",
    "page not available",
]


class PageValidationError(Exception):
    """Raised when the target page is invalid (404, 403, 500, etc.)."""

    def __init__(self, message: str, status_code: int | None = None, final_url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.final_url = final_url


class ExplorationEngine:
    def __init__(
        self,
        exploration_id: uuid.UUID,
        url: str,
        goal: str | None = None,
        event_emitter: Callable[[str, dict], Any] | None = None,
        existing_browser: BrowserSession | None = None,
        credential_id: str | None = None,
        project_id: uuid.UUID | None = None,
        db_session: Any | None = None,
    ):
        self.exploration_id = exploration_id
        self.url = url
        self.goal = goal.strip() if goal else None
        self.event_emitter = event_emitter
        self.credential_id = credential_id
        self.project_id = project_id
        self._db_session = db_session
        self._browser: BrowserSession | None = existing_browser
        self._is_cancelled = False
        self._visited_urls: set[str] = set()
        self._bg_tasks: set[asyncio.Task] = set()
        self._ai_recommendation_reason: str | None = None
        self._last_route_map: list[dict] = []
        self._last_interactive_elements: list[dict] = []
        self._last_persona: str = "User"

    def _spawn_bg(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def cancel_background(self) -> None:
        for task in list(self._bg_tasks):
            task.cancel()

    async def drain_background(self) -> None:
        if self._bg_tasks:
            await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)

    async def _emit(self, event_type: str, payload: dict):
        if self.event_emitter:
            try:
                res = self.event_emitter(event_type, payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning("Error emitting exploration event %s: %s", event_type, e)

    def cancel(self):
        self._is_cancelled = True

    async def _validate_page(self, page, navigation_error: Exception | None = None) -> None:
        """Validate the loaded page is a real application page, not an error page.

        Raises PageValidationError if the page is invalid.
        """
        final_url = page.url
        title = ""
        visible_text = ""

        try:
            title = await page.title()
        except Exception:
            pass

        try:
            visible_text = (await page.inner_text("body"))[:2000]
        except Exception:
            pass

        lower_title = (title or "").lower()
        lower_text = (visible_text or "").lower()

        # Check for Vercel/hosting NOT_FOUND pages
        if "404" in lower_title and "not found" in lower_title:
            raise PageValidationError(
                f"Page returned 404: {final_url}",
                status_code=404,
                final_url=final_url,
            )

        if "vercel" in lower_title and "not found" in lower_title:
            raise PageValidationError(
                f"Vercel 404: Page not found at {final_url}",
                status_code=404,
                final_url=final_url,
            )

        # Check visible text for error page patterns
        for pattern in ERROR_PAGE_PATTERNS:
            if re.search(pattern, lower_text):
                raise PageValidationError(
                    f"Error page detected: {pattern} at {final_url}",
                    final_url=final_url,
                )

        # Check title for error indicators (only if page has very little content)
        if len(lower_text.strip()) < 100:
            for pattern in ERROR_TITLE_PATTERNS:
                if pattern in lower_title:
                    raise PageValidationError(
                        f"Error page detected from title '{title}': {final_url}",
                        final_url=final_url,
                    )

        # Check if page is essentially empty
        if len(lower_text.strip()) < 10:
            raise PageValidationError(
                f"Page is empty or has no usable content: {final_url}",
                final_url=final_url,
            )

    async def _capture_and_emit_screenshot(self, page, full_page: bool = False) -> dict | None:
        """Capture screenshot, emit immediate data URI for live viewport, and upload to S3."""
        if not self._browser or not self._browser.is_started:
            return None
        try:
            try:
                screenshot_bytes = await self._browser.screenshot(full_page=full_page)
            except Exception:
                screenshot_bytes = await self._browser.screenshot(full_page=False)
            parsed = urlparse(page.url)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"

            import base64
            b64_img = base64.b64encode(screenshot_bytes).decode("ascii")
            data_uri = f"data:image/png;base64,{b64_img}"

            screenshot_meta = {
                "url": page.url,
                "path": path,
                "screenshot": data_uri,
                "screenshot_key": f"{self.exploration_id}_{uuid.uuid4().hex[:8]}.png",
                "screenshot_size_bytes": len(screenshot_bytes),
            }

            # Emit immediately so frontend viewport renders in real-time without S3 latency
            await self._emit("browser.screenshot", screenshot_meta)

            # Upload to S3 asynchronously with non-blocking timeout
            async def _bg_upload():
                try:
                    storage_meta = await asyncio.wait_for(
                        asyncio.to_thread(
                            screenshot_storage.save,
                            str(self.exploration_id),
                            screenshot_bytes,
                            page.url,
                        ),
                        timeout=4.0,
                    )
                    if storage_meta.get("screenshot_url"):
                        screenshot_meta["screenshot_url"] = storage_meta["screenshot_url"]
                        await self._emit("browser.screenshot", screenshot_meta)
                except Exception as s3_err:
                    logger.debug("S3 background upload skipped or timed out: %s", s3_err)

            self._spawn_bg(_bg_upload())
            return screenshot_meta
        except Exception as e:
            logger.warning("Could not capture screenshot: %s", e)
            return None

    async def _stream_page_exploration(self, page) -> None:
        """Stream real one-direction browser actions (scrolling, inspecting, section mapping) to the user viewport."""
        try:
            # Measure document height vs viewport height
            scroll_data = await page.evaluate(
                """() => {
                    const docHeight = Math.max(
                        document.body.scrollHeight || 0, document.documentElement.scrollHeight || 0,
                        document.body.offsetHeight || 0, document.documentElement.offsetHeight || 0
                    );
                    const viewHeight = window.innerHeight || 800;
                    return { docHeight, viewHeight };
                }"""
            )
            doc_height = scroll_data.get("docHeight", 800)
            view_height = scroll_data.get("viewHeight", 800)

            # 1. Smoothly scroll through sections covering the entire document height
            max_scroll = max(0, doc_height - view_height)
            if max_scroll > 150:
                num_steps = 4 if max_scroll > 2500 else 3
                steps = [int(max_scroll * (i / num_steps)) for i in range(1, num_steps + 1)]

                for idx, scroll_pos in enumerate(steps, start=1):
                    await self._emit("progress", {
                        "id": f"exp-stream-scroll-{idx}",
                        "message": f"Exploring application sections ({idx}/{len(steps)})",
                        "status": "active",
                    })
                    await page.evaluate(f"window.scrollTo({{ top: {scroll_pos}, behavior: 'smooth' }})")
                    await asyncio.sleep(0.7)
                    await self._capture_and_emit_screenshot(page, full_page=False)

                # Return smoothly to the top of the page
                await page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
                await asyncio.sleep(0.5)
                await self._capture_and_emit_screenshot(page, full_page=False)

            # 2. Inspect and highlight a primary navigation or interactive control
            target_info = await page.evaluate(
                """() => {
                    const candidates = Array.from(document.querySelectorAll('nav a, header a, a.btn, a[href*="/"], button, [role="button"]'));
                    for (const el of candidates) {
                        const rect = el.getBoundingClientRect();
                        const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                        if (rect.width > 24 && rect.height > 18 && rect.top >= 0 && rect.bottom <= window.innerHeight && text.length >= 2 && text.length <= 40) {
                            return {
                                text: text,
                                id: el.id ? '#' + el.id : null,
                                tagName: el.tagName.toLowerCase(),
                            };
                        }
                    }
                    return null;
                }"""
            )

            if target_info and target_info.get("text"):
                label = target_info["text"]
                await self._emit("progress", {
                    "id": "exp-stream-inspect",
                    "message": f"Inspecting navigation: {label}",
                    "status": "active",
                })
                # Visual focus outline
                await page.evaluate(
                    """(info) => {
                        const selector = info.id || info.tagName;
                        const el = document.querySelector(selector);
                        if (el) {
                            el.setAttribute('data-kova-target', 'true');
                            el.style.outline = '2px solid rgba(14, 165, 233, 0.9)';
                            el.style.outlineOffset = '3px';
                        }
                    }""",
                    target_info,
                )
                await asyncio.sleep(0.4)
                await self._capture_and_emit_screenshot(page)
                # Clear focus outline
                await page.evaluate(
                    """() => {
                        const el = document.querySelector('[data-kova-target="true"]');
                        if (el) {
                            el.removeAttribute('data-kova-target');
                            el.style.outline = '';
                            el.style.outlineOffset = '';
                        }
                    }"""
                )
        except Exception as e:
            logger.debug("Page exploration streaming completed: %s", e)

    async def explore(
        self,
        credential: dict | None = None,
        selected_role: str | None = None,
        create_account: bool = False,
    ) -> dict[str, Any]:
        """Runs exploration on target URL.

        Returns a dictionary containing:
        - status: ExplorationStatus
        - discoveries: list of DiscoveryItem dicts
        - candidate_missions: list of DiscoveredMission dicts
        - question: AgentQuestion dict (if role selection needed)
        - credential_request: CredentialRequest dict (if auth required)
        - error_message: str (if failed)
        """
        should_close_browser = True
        try:
            if not self._browser:
                self._browser = BrowserSession()
            if not self._browser.is_started:
                await self._emit("state_change", {"status": "CONNECTING"})
                await self._emit("exploration.started", {"url": self.url})
                await self._emit("progress", {
                    "id": "exp-connecting",
                    "message": f"Connecting to {urlparse(self.url).hostname or self.url}",
                    "status": "active",
                })
                await self._browser.start()

                page = self._browser.page
                page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
                page.set_default_timeout(ACTION_TIMEOUT_MS)

                await self._emit("progress", {
                    "id": "exp-1",
                    "message": f"Connected to {urlparse(self.url).hostname or self.url}",
                    "status": "completed",
                })
            else:
                page = self._browser.page
                page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
                page.set_default_timeout(ACTION_TIMEOUT_MS)

            is_resuming = (credential is not None or selected_role is not None) and bool(
                page.url and page.url != "about:blank"
            )

            if not is_resuming:
                # 1. Navigate to target URL with retry
                await self._emit("state_change", {"status": "LOADING"})
                navigation_error = None
                response = None
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        response = await page.goto(self.url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
                        # Wait for network idle with reasonable bound
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass

                        # For SPAs (React, Vite, Next.js), wait until container elements or text hydrate
                        try:
                            await page.wait_for_function(
                                "() => {"
                                "  const root = document.querySelector('#root, #__next, #app, main, [role=\"main\"], body');"
                                "  return root && (root.children.length > 0 || (root.innerText && root.innerText.trim().length > 20));"
                                "}",
                                timeout=4000,
                            )
                        except Exception:
                            pass

                        # Settle dynamic styles, fonts, and client mounting
                        await asyncio.sleep(1.0)

                        # Trigger lazy-loaded components, images, and intersection observers across the document
                        try:
                            await page.evaluate(
                                """async () => {
                                    const total = Math.min(document.body.scrollHeight || 0, 4500);
                                    let current = 0;
                                    const step = 450;
                                    while (current < total) {
                                        window.scrollBy(0, step);
                                        current += step;
                                        await new Promise((r) => setTimeout(r, 60));
                                    }
                                    window.scrollTo(0, 0);
                                }"""
                            )
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass
                        # Emit URL change so frontend can update address bar immediately
                        await self._emit("page.url_changed", {
                            "url": page.url,
                            "path": urlparse(page.url).path,
                        })
                        navigation_error = None
                        break
                    except Exception as e:
                        navigation_error = e
                        if attempt < max_retries:
                            logger.warning("Navigation attempt %d failed, retrying: %s", attempt + 1, e)
                            await asyncio.sleep(2)
                            continue

                # Handle navigation failure after all retries exhausted
                if navigation_error is not None:
                    diagnostics = []
                    try:
                        title = await page.title()
                        if title:
                            diagnostics.append(f"title: {title}")
                    except Exception:
                        pass

                    try:
                        current_url = page.url
                        diagnostics.append(f"final_url: {current_url}")
                    except Exception:
                        pass

                    try:
                        visible_text = (await page.inner_text("body"))[:500]
                        if visible_text.strip():
                            diagnostics.append(f"content: {visible_text[:200]}")
                    except Exception:
                        pass

                    diag_str = "; ".join(diagnostics) if diagnostics else "no diagnostics available"
                    error_msg = f"Navigation failed for {self.url}: {navigation_error} [{diag_str}]"

                    await self._emit("state_change", {"status": "FAILED"})
                    await self._emit("exploration.failed", {"error": error_msg})
                    return {
                        "status": ExplorationStatus.FAILED,
                        "error_message": error_msg,
                        "discoveries": [],
                        "candidate_missions": [],
                    }

                current_url = page.url
                self._visited_urls.add(current_url)

                await self._emit("state_change", {"status": "VALIDATING_PAGE"})
                await self._emit("progress", {
                    "id": "exp-validating",
                    "message": "Validating target page",
                    "status": "active",
                })

                # 2. Validate the loaded page
                try:
                    await self._validate_page(page, navigation_error)
                except PageValidationError as e:
                    error_msg = str(e)
                    if hasattr(response, 'status') and response:
                        error_msg = f"HTTP {response.status}: {error_msg}"
                    await self._emit("state_change", {"status": "FAILED"})
                    await self._emit("exploration.failed", {"error": error_msg})
                    return {
                        "status": ExplorationStatus.FAILED,
                        "error_message": error_msg,
                        "discoveries": [],
                        "candidate_missions": [],
                    }

                # Emit page.loaded with title and capture initial rendered screenshot
                page_title = await page.title()
                page_event = {
                    "url": current_url,
                    "title": page_title,
                }
                await self._emit("page.loaded", page_event)

                # Capture and stream fully rendered initial snapshot immediately (standard viewport)
                await self._capture_and_emit_screenshot(page, full_page=False)

                # 3. Observe initial page
                await self._emit("state_change", {"status": "EXPLORING"})
                await self._emit("progress", {
                    "id": "exp-observe",
                    "message": "Observing application page",
                    "status": "active",
                })
                observation = await self._browser.observe()
                await self._emit("agent.observed", {
                    "elements_count": len(observation.get("elements", [])),
                    "forms_count": len(observation.get("forms", [])),
                })

                # Stream real one-direction browser actions (sections scroll & navigation inspection)
                await self._stream_page_exploration(page)

                # 3. Check for authentication requirement
                from app.engine.browser.auth import classify_auth_page, observe_auth_signals
                auth_bundle = await observe_auth_signals(page, page.url)
                auth_classification = classify_auth_page(auth_bundle)
                await self._emit("auth_classified", {
                    "kind": auth_classification.kind,
                    "confidence": auth_classification.confidence,
                    "reasoning": auth_classification.reasoning,
                    "url": page.url,
                })
                is_auth_required = (
                    auth_classification.kind in {"login", "signup", "magic_link", "otp_verification", "oauth_redirect"}
                    or await self._detect_authentication(page, observation)
                )

                if is_auth_required and not credential:
                    should_close_browser = False
                    await self._emit("state_change", {"status": "AUTH_REQUIRED"})
                    hostname = urlparse(self.url).hostname or "application"
                    auth_reason = (
                        f"This product requires an account. Kova needs a test account "
                        f"to continue exploring {hostname}."
                    )
                    credential_request = CredentialRequest(
                        type="login",
                        reason=auth_reason,
                    ).model_dump()

                    await self._emit("auth.required", {"request": credential_request})
                    await self._emit("progress", {
                        "id": "exp-auth",
                        "message": "Found authentication barrier",
                        "status": "completed",
                    })

                    return {
                        "status": ExplorationStatus.AUTH_REQUIRED,
                        "credential_request": credential_request,
                        "discoveries": [
                            {"label": "Authentication", "description": "Sign in / registration required to access application workspace"}
                        ],
                        "candidate_missions": [],
                    }

            # 4. Handle authentication if credentials provided
            if credential:
                auth_mode_label = "Creating account" if create_account else "Authenticating"
                await self._emit("progress", {
                    "id": "exp-auth-nav",
                    "message": f"Locating {'registration' if create_account else 'sign-in'} view",
                    "status": "active",
                })

                # Ensure browser is positioned on the authentication form (navigating or opening modal if needed)
                navigated_auth = await self._ensure_on_auth_form(page, is_signup=create_account)
                if navigated_auth:
                    await self._emit("progress", {
                        "id": "exp-auth-nav",
                        "message": f"Found {'registration' if create_account else 'sign-in'} view on {page.url}",
                        "status": "completed",
                    })

                await self._emit("state_change", {"status": "AUTHENTICATING"})
                await self._emit("authenticating", {})
                await self._emit("progress", {
                    "id": "exp-auth-progress",
                    "message": f"{auth_mode_label} as {credential.get('email')}",
                    "status": "active",
                })

                auth_success, auth_detail = await self._perform_login(page, credential, is_signup=create_account)
                if not auth_success:
                    should_close_browser = False
                    error_msg = auth_detail or "Authentication failed with provided credentials."
                    await self._emit("auth.failed", {"error": error_msg})
                    await self._emit("state_change", {"status": "AUTH_REQUIRED"})
                    return {
                        "status": ExplorationStatus.AUTH_REQUIRED,
                        "error_message": error_msg,
                        "credential_request": CredentialRequest(
                            type="login",
                            reason=error_msg,
                        ).model_dump(),
                        "discoveries": [],
                        "candidate_missions": [],
                    }

                await self._emit("authenticated", {})
                await self._emit("progress", {
                    "id": "exp-auth-progress",
                    "message": f"{'Account created' if create_account else 'Signed in'} as {credential.get('email')}",
                    "status": "completed",
                })

                # Re-observe post-auth page
                await asyncio.sleep(1.0)
                observation = await self._browser.observe()
                await self._capture_and_emit_screenshot(page)
            elif is_resuming:
                observation = await self._browser.observe()

            # 5. Detect multiple roles if not yet selected
            if not selected_role:
                detected_roles = await self._detect_roles(page, observation)
                if len(detected_roles) >= 2:
                    should_close_browser = False
                    await self._emit("state_change", {"status": "ASKING"})
                    role_options = [
                        AgentQuestionOption(
                            id=r["id"],
                            label=r["label"],
                            description=r["description"],
                            icon=r.get("icon", "person"),
                        )
                        for r in detected_roles
                    ]
                    question = AgentQuestion(
                        id="role-selection",
                        title=f"I found {len(detected_roles)} user roles. Which should I explore?",
                        description="Choose the primary workspace for Kova to map journeys.",
                        type="role",
                        options=role_options,
                    ).model_dump()

                    await self._emit("question", {"question": question})
                    return {
                        "status": ExplorationStatus.ASKING,
                        "question": question,
                        "discoveries": [],
                        "candidate_missions": [],
                    }

            # Fast-path candidate missions (emitted immediately from initial DOM observation in <3s)
            fast_missions = self._generate_fast_path_missions(page, observation, self.goal)
            if fast_missions:
                await self._emit("missions", {
                    "missions": [m.model_dump() for m in fast_missions],
                    "recommendation": self._generate_recommendation(fast_missions),
                })

            # 6. Discover workflows and map journeys
            await self._emit("state_change", {"status": "DISCOVERING"})
            await self._emit("progress", {
                "id": "exp-discover",
                "message": "Mapping user journeys and application workspace",
                "status": "active",
            })

            discoveries, missions = await self._discover_workflows(page, observation, selected_role)
            await self._capture_and_emit_screenshot(page, full_page=False)

            await self._emit("progress", {
                "id": "exp-discover",
                "message": f"Identified {len(missions)} actionable user journeys",
                "status": "completed",
            })

            await self._emit("state_change", {"status": "PLANNING"})
            await self._emit("discovery", {"discoveries": [d.model_dump() for d in discoveries]})
            await self._emit("missions", {
                "missions": [m.model_dump() for m in missions],
                "recommendation": self._generate_recommendation(missions),
            })
            # Ensure missions and discoveries are processed before ready state_change
            await asyncio.sleep(0.05)

            # Fast synthesis of DiscoveryResult without blocking READY
            discovery_result = self._synthesize_fast_discovery_result(
                page_url=getattr(page, "url", self.url),
                page_title=observation.get("title", ""),
                route_map=self._last_route_map,
                interactive_elements=self._last_interactive_elements,
                persona_name=self._last_persona,
            )

            await self._emit("state_change", {"status": "READY"})
            await self._emit("ready", {})

            should_close_browser = False
            return {
                "status": ExplorationStatus.READY,
                "discoveries": [d.model_dump() for d in discoveries],
                "candidate_missions": [m.model_dump() for m in missions],
                "discovery_result": discovery_result.model_dump(mode="json") if discovery_result else None,
            }

        finally:
            if self._browser and should_close_browser:
                self.cancel_background()
                await self._browser.close()

    async def navigate_browser(self, action: str) -> dict[str, Any]:
        """Navigate the browser (back, forward, or reload).

        Args:
            action: One of 'back', 'forward', 'reload'

        Returns:
            dict with url, title, and path after navigation
        """
        if not self._browser or not self._browser.page:
            return {"error": "No active browser session"}

        page = self._browser.page

        try:
            if action == "back":
                await page.go_back(wait_until="domcontentloaded")
            elif action == "forward":
                await page.go_forward(wait_until="domcontentloaded")
            elif action == "reload":
                await page.reload(wait_until="domcontentloaded")
            else:
                return {"error": f"Unknown navigation action: {action}"}

            # Wait for page to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # Emit URL change
            current_url = page.url
            await self._emit("page.url_changed", {
                "url": current_url,
                "path": urlparse(current_url).path,
            })

            # Capture screenshot
            await self._capture_and_emit_screenshot(page)

            return {
                "url": current_url,
                "path": urlparse(current_url).path,
                "title": await page.title(),
            }

        except Exception as e:
            logger.warning("Browser navigation failed: %s", e)
            return {"error": str(e)}

    async def _detect_authentication(self, page, observation: dict) -> bool:
        """Determines if the current view is an authentication barrier.

        Uses graduated signal detection:
        - Strong signal (URL pattern): immediately returns True
        - Medium signal (password input + auth form): requires page to be mostly login UI
        - Weak signal (email input + sign-in button): requires corroborating evidence
        """
        current_url = page.url.lower()

        # STRONG: URL contains auth path — this IS a login page
        auth_url_keywords = ["/login", "/signin", "/sign-in", "/auth/login", "/session/new", "/log-in"]
        if any(kw in current_url for kw in auth_url_keywords):
            return True

        elements = observation.get("elements", [])
        visible_text = (observation.get("text", "") or "").lower()

        # Count total interactive elements (indicates page complexity)
        total_interactive = len(elements)

        # Count auth-specific elements
        has_password_input = any(
            el.get("type") == "input" and el.get("input_type") == "password"
            for el in elements
        )
        has_email_input = any(
            el.get("type") == "input"
            and any(
                field in (el.get("name", "") + el.get("label", "") + el.get("placeholder", "")).lower()
                for field in ["email", "username", "login", "user"]
            )
            for el in elements
        )
        has_auth_button = any(
            el.get("type") == "button"
            and any(
                btn_word in el.get("name", "").lower()
                for btn_word in ["sign in", "login", "log in"]
            )
            for el in elements
        )

        # MEDIUM: Password input present — but only trigger if page is predominantly login UI
        # If there are many other interactive elements (nav, content, etc.), it's a landing page with login
        if has_password_input:
            auth_element_count = sum(1 for el in elements if el.get("type") == "input")
            non_auth_elements = total_interactive - auth_element_count

            # Page is mostly login inputs with little else → auth barrier
            if non_auth_elements <= 2:
                return True

            # Check text for prominent login prompts that dominate the page
            login_text_signals = [
                "sign in to your account",
                "log in to continue",
                "enter your credentials",
                "please sign in",
                "please log in",
                "access your account",
            ]
            if any(signal in visible_text for signal in login_text_signals):
                return True

            # Otherwise — landing page with a login section, not an auth barrier
            return False

        # WEAK: Email + sign-in button but no password — might be SSO or magic link
        # Only trigger if page has very few other elements (mostly auth UI)
        if has_email_input and has_auth_button:
            if total_interactive <= 4:
                return True

    async def _extract_visible_auth_error(self, page) -> str | None:
        """Extracts visible error message from explicit UI alert elements."""
        error_selectors = [
            '[role="alert"]',
            '[aria-invalid="true"]',
            '.error',
            '.alert',
            '[class*="error" i]',
            '[class*="alert" i]',
            '[class*="danger" i]',
            '[id*="error" i]',
            '.text-destructive',
            '.text-red-500',
            '.text-red-600',
        ]
        auth_error_keywords = [
            "invalid credentials", "incorrect password", "wrong password",
            "user not found", "no account found", "email not found",
            "invalid email", "invalid login", "login failed",
            "authentication failed", "could not sign in", "couldn't sign in",
            "unable to sign in", "sign in failed", "error logging in",
            "wrong email or password", "incorrect email or password",
            "invalid email or password", "those credentials don't match",
            "credentials are incorrect", "account not found", "does not exist",
            "unauthorized", "forbidden",
        ]
        try:
            for sel in error_selectors:
                elements = await page.query_selector_all(sel)
                for el in elements:
                    try:
                        if not await el.is_visible():
                            continue
                        text = (await el.inner_text()).strip()
                        if not text or len(text) < 4:
                            continue
                        text_lower = text.lower()
                        if any(kw in text_lower for kw in auth_error_keywords):
                            return text[:200]
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("Error checking auth alert elements: %s", e)
        return None

    async def _find_submit_button(self, page, password_input):
        """Finds genuine submit button for credentials form, excluding OAuth."""
        oauth_exclude = [
            "google", "github", "apple", "microsoft", "sso", "saml", "passkey",
            "facebook", "twitter", "magic link", "forgot", "reset",
        ]

        # 1. Look inside the ancestor <form> first
        try:
            form = password_input.locator("xpath=ancestor::form").first
            form_count = form.count()
            if inspect.isawaitable(form_count):
                form_count = await form_count
            if form_count > 0:
                for sel in ['button[type="submit"]', 'input[type="submit"]', 'button']:
                    buttons = form.locator(sel)
                    count = buttons.count()
                    if inspect.isawaitable(count):
                        count = await count
                    for i in range(count):
                        btn = buttons.nth(i)
                        if inspect.isawaitable(btn):
                            btn = await btn
                        try:
                            vis = btn.is_visible(timeout=1000) if hasattr(btn, "is_visible") else False
                            if inspect.isawaitable(vis):
                                vis = await vis
                            if not vis:
                                continue
                            txt = btn.inner_text(timeout=1000) if hasattr(btn, "inner_text") else ""
                            if inspect.isawaitable(txt):
                                txt = await txt
                            text = (txt or "").lower()
                            if any(prov in text for prov in oauth_exclude):
                                continue
                            return btn
                        except Exception:
                            continue
        except Exception:
            pass

        # 2. Page-level search with exact priority
        candidates = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Create account"), button:has-text("Create Account"), button:has-text("Sign up"), button:has-text("Sign Up"), button:has-text("Register")',
            '#login-btn, #submit-btn, [data-testid*="login" i], [data-testid*="submit" i]',
            'button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Login")',
            'button:has-text("Continue"), button:has-text("Submit"), button:has-text("Next")',
            'a[role="button"]:has-text("Sign in"), a[role="button"]:has-text("Log in")',
        ]
        for sel in candidates:
            try:
                buttons = page.locator(sel)
                count = buttons.count()
                if inspect.isawaitable(count):
                    count = await count
                for i in range(count):
                    btn = buttons.nth(i)
                    if inspect.isawaitable(btn):
                        btn = await btn
                    try:
                        vis = btn.is_visible(timeout=1000) if hasattr(btn, "is_visible") else False
                        if inspect.isawaitable(vis):
                            vis = await vis
                        if not vis:
                            continue
                        txt = btn.inner_text(timeout=1000) if hasattr(btn, "inner_text") else ""
                        if inspect.isawaitable(txt):
                            txt = await txt
                        text = (txt or "").lower()
                        if any(prov in text for prov in oauth_exclude):
                            continue
                        return btn
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    async def _perform_login(self, page, credential: dict, is_signup: bool = False) -> tuple[bool, str]:
        """Fills login or signup form, submits credentials, and verifies navigation."""
        email = credential.get("email", "")
        password = credential.get("password", "")

        # Check all frames (top-level page plus any auth iframes)
        frames = [page]
        try:
            for f in getattr(page, "frames", []):
                if f not in frames:
                    frames.append(f)
        except Exception:
            pass

        name_selector = (
            'input[name="name" i], '
            'input[name*="full_name" i], '
            'input[name*="fullname" i], '
            'input[autocomplete="name" i], '
            'input[placeholder*="name" i], '
            'input[placeholder*="Elvis" i], '
            'input[aria-label*="name" i], '
            'input[id*="name" i]:not([id*="user" i])'
        )
        email_selector = (
            'input[type="email"], '
            'input[name="email" i], '
            'input[name="username" i], '
            'input[name="identifier" i], '
            'input[name="login" i], '
            'input[name="user" i], '
            'input[autocomplete="email" i], '
            'input[autocomplete="username" i], '
            '#email, #username, #identifier, '
            'input[placeholder*="email" i], '
            'input[placeholder*="username" i], '
            'input[placeholder*="phone" i], '
            'input[aria-label*="email" i], '
            'input[aria-label*="username" i], '
            'input[data-testid*="email" i], '
            'input[data-testid*="username" i]'
        )
        fallback_email_selector = (
            'input:not([type="password"]):not([type="hidden"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"])'
        )
        password_selector = (
            'input[type="password"], '
            'input[name="password" i], '
            'input[name="pass" i], '
            'input[name*="password" i], '
            'input[autocomplete*="password" i], '
            '#password, #pass, '
            'input[placeholder*="password" i], '
            'input[aria-label*="password" i], '
            'input[data-testid*="password" i]'
        )

        async def _find_inputs():
            found_name, found_email, found_pwd, found_scope = None, None, None, page
            for scope in frames:
                try:
                    loc = scope.locator(email_selector).first
                    if await loc.is_visible(timeout=1000):
                        found_email = loc
                        found_scope = scope
                except Exception:
                    pass

                try:
                    loc = scope.locator(password_selector).first
                    if await loc.is_visible(timeout=1000):
                        found_pwd = loc
                        found_scope = scope
                except Exception:
                    pass

                if not found_email:
                    try:
                        loc = scope.locator(fallback_email_selector).first
                        if await loc.is_visible(timeout=600):
                            found_email = loc
                            found_scope = scope
                    except Exception:
                        pass

                if found_email or found_pwd:
                    try:
                        loc = scope.locator(name_selector).first
                        if await loc.is_visible(timeout=300):
                            found_name = loc
                    except Exception:
                        pass
                    break
            return found_name, found_email, found_pwd, found_scope

        name_input, email_input, password_input, active_scope = await _find_inputs()

        # If inputs not found, attempt navigation or modal trigger
        if not email_input or not password_input:
            navigated = await self._ensure_on_auth_form(page, is_signup=is_signup)
            if navigated:
                name_input, email_input, password_input, active_scope = await _find_inputs()

        # Semantic AI fallback if heuristic selectors failed to locate inputs
        if not email_input or not password_input:
            try:
                from app.engine.browser.auth import find_auth_inputs_semantically
                ai_prov = get_ai_provider()
                s_name, s_email, s_pwd, s_scope = await find_auth_inputs_semantically(
                    page, provider=ai_prov, is_signup=is_signup
                )
                if s_email or s_pwd:
                    name_input = name_input or s_name
                    email_input = email_input or s_email
                    password_input = password_input or s_pwd
                    active_scope = s_scope or active_scope
            except Exception as e:
                logger.debug("Explorer semantic auth fallback error: %s", e)

        # Multi-step authentication: email entered on step 1, password appears on step 2
        if email_input and not password_input:
            try:
                await email_input.focus()
                await email_input.fill(email)
                await email_input.evaluate(
                    "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                )
                submit_btn = await self._find_submit_button(page, email_input)
                if submit_btn:
                    await submit_btn.click(timeout=2000)
                    await asyncio.sleep(1.0)
                    name_input, email_input, password_input, active_scope = await _find_inputs()
                    if not password_input:
                        try:
                            from app.engine.browser.auth import find_auth_inputs_semantically
                            ai_prov = get_ai_provider()
                            _, _, password_input, active_scope = await find_auth_inputs_semantically(
                                page, provider=ai_prov, is_signup=is_signup
                            )
                        except Exception:
                            pass
            except Exception as ex:
                logger.debug("Multi-step email submit attempt: %s", ex)

        if name_input:
            try:
                display_name = credential.get("name") or "Kova Tester"
                await name_input.focus()
                await name_input.fill(display_name)
                await name_input.evaluate(
                    "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                )
            except Exception:
                pass

        if not email_input and not password_input:
            return False, "Could not find email or password input fields on the page."
        if not email_input:
            return False, "Could not find email or username input field on the page."
        if not password_input:
            # Check if email-only submission succeeded or sent verification
            current_url = getattr(page, "url", "").lower()
            if any(kw in current_url for kw in ["/dashboard", "/app", "/home", "/welcome", "/verify"]):
                return True, ""
            try:
                body_text = (await page.inner_text("body", timeout=1000) or "").lower()
                if any(term in body_text for term in ["check your email", "magic link", "verification link", "verification email", "we sent a link"]):
                    return True, "Verification email or magic link dispatched."
            except Exception:
                pass
            return False, "Could not find password input field on the page."

        try:
            # Focus, fill, and dispatch synthetic change events for React/SPA controlled inputs
            await email_input.focus()
            await email_input.fill(email)
            try:
                await email_input.evaluate(
                    "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                )
            except Exception:
                pass

            # Fill all visible password inputs (handles password + confirm password fields)
            try:
                pwd_locs = await page.locator(password_selector).all()
                for p_loc in pwd_locs:
                    try:
                        if await p_loc.is_visible(timeout=500):
                            await p_loc.focus()
                            await p_loc.fill(password)
                            await p_loc.evaluate(
                                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                            )
                    except Exception:
                        pass
            except Exception:
                await password_input.focus()
                await password_input.fill(password)
                try:
                    await password_input.evaluate(
                        "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                    )
                except Exception:
                    pass

            # Automatically agree to terms/privacy checkboxes if required on registration forms
            terms_selector = (
                'input[type="checkbox"][name*="term" i], '
                'input[type="checkbox"][name*="agree" i], '
                'input[type="checkbox"][id*="term" i], '
                'input[type="checkbox"][id*="agree" i], '
                'input[type="checkbox"][aria-label*="term" i], '
                'input[type="checkbox"][aria-label*="agree" i]'
            )
            try:
                terms_cb = page.locator(terms_selector).first
                if await terms_cb.is_visible(timeout=500):
                    if not await terms_cb.is_checked():
                        await terms_cb.check()
            except Exception:
                pass

            # Capture live screenshot showing credentials injected into form
            await self._capture_and_emit_screenshot(page)

            # Brief pause for state update/client-side validation
            await asyncio.sleep(0.2)

            # Locate authentic submit button (avoiding OAuth providers)
            submit_btn = await self._find_submit_button(page, password_input)

            # Attempt submission via submit button
            submitted = False
            if submit_btn:
                try:
                    await submit_btn.scroll_into_view_if_needed(timeout=1500)
                    await submit_btn.click(timeout=3000)
                    submitted = True
                except Exception:
                    try:
                        await submit_btn.click(force=True, timeout=2000)
                        submitted = True
                    except Exception:
                        pass

            # Fallback to Enter key and requestSubmit() only if submit button was not present or failed
            if not submitted:
                try:
                    await password_input.focus()
                    await password_input.press("Enter")
                    submitted = True
                except Exception:
                    pass

                if not submitted:
                    try:
                        await password_input.evaluate("el => el.form ? el.form.requestSubmit() : null")
                    except Exception:
                        pass

            # Capture live screenshot immediately after submit trigger (in background so polling begins promptly)
            try:
                self._spawn_bg(self._capture_and_emit_screenshot(page))
            except Exception:
                pass

            # Wait briefly for page to begin responding to submit
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass

            # Poll for authentication resolution (URL change, password detachment, or explicit error alert)
            auth_url_indicators = [
                "/login", "/signin", "/sign-in", "/auth/login", "/log-in", "/session/new",
                "/signup", "/sign-up", "/register", "/auth/signup", "/registration"
            ]
            max_wait_seconds = 8.0
            poll_interval = 0.5
            elapsed = 0.0

            while elapsed < max_wait_seconds:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                # 1. Check for explicit visible error banner
                auth_error = await self._extract_visible_auth_error(page)
                if auth_error:
                    logger.info("Auth submission failed — explicit error banner detected: %s", auth_error)
                    return False, auth_error

                # 2. Check if navigated away from auth URL
                current_url = page.url.lower()
                stayed_on_auth = any(kw in current_url for kw in auth_url_indicators)

                # 3. Check if password field is still visible
                is_still_password = False
                try:
                    is_still_password = await page.locator('input[type="password"]').first.is_visible(timeout=300)
                except Exception as e:
                    logger.debug("Password field check failed (likely navigated): %s", e)
                    is_still_password = False

                # If URL changed away from login/signup, or password field detached/hidden
                if not stayed_on_auth or not is_still_password:
                    logger.info("Auth succeeded — navigated away or password field detached (elapsed: %.1fs)", elapsed)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=3000)
                    except Exception:
                        pass
                    return True, ""

            # Check if still stuck on auth page after polling timeout
            auth_error = await self._extract_visible_auth_error(page)
            if auth_error:
                return False, auth_error

            current_url = page.url.lower()
            stayed_on_auth = any(kw in current_url for kw in auth_url_indicators)
            is_still_password = False
            try:
                is_still_password = await page.locator('input[type="password"]').first.is_visible(timeout=500)
            except Exception:
                is_still_password = False

            if stayed_on_auth and is_still_password:
                logger.info("Auth failed — still on auth page with password field visible after %.1fs", max_wait_seconds)
                fail_msg = "Account creation failed. The registration form may require additional verification or custom fields." if is_signup else "Login failed. The credentials may be incorrect or the page requires additional input."
                return False, fail_msg

            return True, ""

        except Exception as e:
            logger.warning("Error during login execution: %s", e)
            return False, f"Login execution error: {e}"

    async def _has_visible_auth_inputs(self, page) -> bool:
        """Returns True if email/username or password inputs are visible in page or frames."""
        frames = [page]
        try:
            frames.extend(getattr(page, "frames", []))
        except Exception:
            pass

        email_selector = (
            'input[type="email"], '
            'input[name="email" i], '
            'input[name="username" i], '
            'input[name="identifier" i], '
            'input[name="login" i], '
            'input[name="user" i], '
            'input[autocomplete="email" i], '
            'input[autocomplete="username" i], '
            '#email, #username, #identifier, '
            'input[placeholder*="email" i], '
            'input[placeholder*="username" i], '
            'input[aria-label*="email" i], '
            'input[aria-label*="username" i], '
            'input[data-testid*="email" i], '
            'input[data-testid*="username" i]'
        )
        password_selector = (
            'input[type="password"], '
            'input[name="password" i], '
            'input[name="pass" i], '
            'input[name*="password" i], '
            'input[autocomplete*="password" i], '
            '#password, #pass, '
            'input[id*="pass" i], '
            'input[placeholder*="password" i], '
            'input[aria-label*="password" i], '
            'input[data-testid*="password" i]'
        )

        for scope in frames:
            try:
                el_email = scope.locator(email_selector).first
                el_pwd = scope.locator(password_selector).first
                if await el_pwd.is_visible(timeout=800) or await el_email.is_visible(timeout=800):
                    return True
                any_pwd = scope.locator('input[type="password"], input[name*="pass" i]').first
                if await any_pwd.is_visible(timeout=600):
                    return True
                dialog_inputs = scope.locator('dialog input:not([type="hidden"]), [role="dialog"] input:not([type="hidden"]), form input:not([type="hidden"])').first
                if await dialog_inputs.is_visible(timeout=400):
                    return True
            except Exception:
                continue

        current_url = getattr(page, "url", "").lower()
        if any(kw in current_url for kw in ["/login", "/signin", "/signup", "/register", "/auth/"]):
            for scope in frames:
                try:
                    any_input = scope.locator('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="submit"])').first
                    if await any_input.is_visible(timeout=500):
                        return True
                except Exception:
                    continue
        return False

    async def _ensure_on_auth_form(self, page, is_signup: bool = False) -> bool:
        """Ensures the browser is on the login or signup page/form before credential injection."""
        # 1. Check if auth inputs are already visible
        if await self._has_visible_auth_inputs(page):
            # If on signin form but signup requested (or vice versa), check for toggle/switch link
            toggle_selector = (
                'a:has-text("Sign up"), button:has-text("Sign up"), a:has-text("Create an account"), a:has-text("Register")'
                if is_signup else
                'a:has-text("Sign in"), button:has-text("Sign in"), a:has-text("Log in"), button:has-text("Log in")'
            )
            try:
                toggle_btn = page.locator(toggle_selector).first
                if await toggle_btn.is_visible(timeout=500):
                    await toggle_btn.click(timeout=1500)
                    await asyncio.sleep(1.0)
            except Exception:
                pass
            return True

        # 2. Look for entrance link or button on current page
        if is_signup:
            selectors = [
                'a:has-text("Sign up")', 'button:has-text("Sign up")',
                'a:has-text("Sign Up")', 'button:has-text("Sign Up")',
                'a:has-text("Create account")', 'button:has-text("Create account")',
                'a:has-text("Create Account")', 'button:has-text("Create Account")',
                'a:has-text("Get started")', 'button:has-text("Get started")',
                'a:has-text("Get Started")', 'button:has-text("Get Started")',
                'a:has-text("Start Learning")', 'button:has-text("Start Learning")',
                'a:has-text("Start learning")', 'button:has-text("Start learning")',
                'a:has-text("Start Free")', 'button:has-text("Start Free")',
                'a:has-text("Try for Free")', 'button:has-text("Try for Free")',
                'a:has-text("Register")', 'button:has-text("Register")',
                'a:has-text("Join")', 'button:has-text("Join")',
                'a[href*="signup" i]', 'a[href*="register" i]', 'a[href*="create-account" i]',
            ]
            fallback_paths = ["/auth/signup", "/signup", "/sign-up", "/register", "/auth/register"]
        else:
            selectors = [
                'a:has-text("Sign in")', 'button:has-text("Sign in")',
                'a:has-text("Sign In")', 'button:has-text("Sign In")',
                'a:has-text("Log in")', 'button:has-text("Log in")',
                'a:has-text("Log In")', 'button:has-text("Log In")',
                'a:has-text("Login")', 'button:has-text("Login")',
                'a:has-text("Account")', 'button:has-text("Account")',
                'a[href*="signin" i]', 'a[href*="login" i]', 'a[href*="sign-in" i]', 'a[href*="log-in" i]',
            ]
            fallback_paths = ["/auth/signin", "/auth/login", "/login", "/signin", "/sign-in"]

        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=600):
                    href = await el.get_attribute("href")
                    if href and href.startswith("/"):
                        parsed = urlparse(page.url)
                        target = f"{parsed.scheme}://{parsed.netloc}{href}"
                        await page.goto(target, wait_until="domcontentloaded", timeout=5000)
                        await asyncio.sleep(1.0)
                        if await self._has_visible_auth_inputs(page):
                            return True
                    elif href and href.startswith("http"):
                        await page.goto(href, wait_until="domcontentloaded", timeout=5000)
                        await asyncio.sleep(1.0)
                        if await self._has_visible_auth_inputs(page):
                            return True
                    else:
                        await el.click(timeout=1500)
                        await asyncio.sleep(1.0)
                        if await self._has_visible_auth_inputs(page):
                            return True
            except Exception:
                continue

        # 3. Direct probe of standard paths on the host
        current_url = getattr(page, "url", "")
        if current_url:
            parsed = urlparse(current_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            for p in fallback_paths:
                try:
                    cand_url = f"{base}{p}"
                    resp = await page.request.get(cand_url, timeout=2000, fail_on_status_code=False)
                    if 200 <= resp.status < 400:
                        await page.goto(cand_url, wait_until="domcontentloaded", timeout=4000)
                        await asyncio.sleep(1.0)
                        if await self._has_visible_auth_inputs(page):
                            return True
                except Exception:
                    continue

        # 4. AI / semantic entrance element fallback
        try:
            from app.engine.browser.auth import find_auth_entrance_semantically
            opened = await find_auth_entrance_semantically(page, provider=get_ai_provider(), is_signup=is_signup)
            if opened:
                await asyncio.sleep(1.0)
                if await self._has_visible_auth_inputs(page):
                    return True
        except Exception as e:
            logger.debug("Semantic auth entrance fallback error: %s", e)

        return False

    async def _find_signup_link(self, page) -> str | None:
        """Looks for a signup/register link on the current page and returns its URL."""
        import inspect

        signup_selectors = [
            'a:has-text("Sign up")',
            'a:has-text("Create account")',
            'a:has-text("Create Account")',
            'a:has-text("Register")',
            'a:has-text("Join")',
            'a:has-text("Get started")',
            'a:has-text("Get Started")',
            'a[href*="signup"]',
            'a[href*="register"]',
            'a[href*="create-account"]',
            'a[href*="create_account"]',
            'button:has-text("Sign up")',
            'button:has-text("Create account")',
            'button:has-text("Register")',
        ]

        for sel in signup_selectors:
            try:
                elements = page.locator(sel)
                count = elements.count()
                if inspect.isawaitable(count):
                    count = await count
                if count > 0:
                    el = elements.first
                    if inspect.isawaitable(el):
                        el = await el
                    try:
                        vis = el.is_visible()
                        if inspect.isawaitable(vis):
                            vis = await vis
                        if not vis:
                            continue
                    except Exception:
                        continue

                    # Get href if it's a link
                    try:
                        href = el.get_attribute("href")
                        if inspect.isawaitable(href):
                            href = await href
                        if href:
                            if href.startswith("/"):
                                from urllib.parse import urlparse as _urlparse
                                parsed = _urlparse(page.url)
                                return f"{parsed.scheme}://{parsed.netloc}{href}"
                            elif href.startswith("http"):
                                return href
                    except Exception:
                        pass

                    # Try clicking and getting the resulting URL
                    try:
                        current_url = page.url
                        await el.click()
                        await asyncio.sleep(2)
                        new_url = page.url
                        if new_url != current_url:
                            return new_url
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    async def _detect_roles(self, page, observation: dict) -> list[dict]:
        """Detects if application provides distinct roles or candidate workspaces.

        Detection sources:
        1. Explicit DOM role switchers (<select name="role">, radio options, data-role attributes).
        2. Explicit multi-role login entry points ("Sign in as Student", "Sign in as Instructor").
        3. Multi-namespace route structure discovered from on-page navigation links (/admin vs /app, /seller vs /buyer).

        Returns a list of role option dicts for AgentQuestion if 2 or more distinct roles/workspaces
        are detected. Returns empty list if unified or public.
        """
        roles_by_id: dict[str, dict] = {}

        # 1. Inspect DOM strictly for role-switcher controls, select dropdowns, and portal buttons
        if page:
            try:
                dom_roles = await page.evaluate("""
                    () => {
                        const detected = [];
                        // Check select dropdowns
                        document.querySelectorAll('select').forEach(sel => {
                            const name = (sel.name || sel.id || sel.getAttribute('aria-label') || '').toLowerCase();
                            if (name.includes('role') || name.includes('user_type') || name.includes('account_type') || name.includes('persona')) {
                                Array.from(sel.options).forEach(opt => {
                                    const val = (opt.value || '').trim();
                                    const txt = (opt.textContent || '').trim();
                                    const label = txt || val;
                                    if (label && label.length < 30 && !['select', 'choose', 'all', 'none'].includes(label.toLowerCase())) {
                                        const cleanId = (val || txt).toLowerCase().replace(/[^a-z0-9_-]/g, '_');
                                        detected.push({
                                            id: cleanId,
                                            label: label,
                                            description: `Role option from ${sel.name || 'role selector'}`,
                                            icon: cleanId.includes('admin') ? 'admin_panel_settings' : 'person',
                                            source: 'select'
                                        });
                                    }
                                });
                            }
                        });

                        // Check explicit data attributes
                        document.querySelectorAll('[data-role], [data-persona], [data-account-type]').forEach(el => {
                            const r = (el.getAttribute('data-role') || el.getAttribute('data-persona') || el.getAttribute('data-account-type') || '').trim();
                            if (r && r.length < 30 && !['button', 'tab', 'menu'].includes(r.toLowerCase())) {
                                const cleanId = r.toLowerCase().replace(/[^a-z0-9_-]/g, '_');
                                detected.push({
                                    id: cleanId,
                                    label: r.charAt(0).toUpperCase() + r.slice(1),
                                    description: `Workspace indicated by [data-role="${r}"]`,
                                    icon: cleanId.includes('admin') ? 'admin_panel_settings' : 'badge',
                                    source: 'data_attribute'
                                });
                            }
                        });

                        // Check explicit action buttons with 'sign in as <role>', 'login as <role>', or '<role> portal'
                        const roleMatches = [
                            ['admin', 'Administrator', 'System management, organization settings, and member controls', 'admin_panel_settings'],
                            ['student', 'Student', 'Learner workspace with material access and courses', 'school'],
                            ['instructor', 'Instructor', 'Teaching workspace with course creation and grading tools', 'psychology'],
                            ['teacher', 'Teacher', 'Educator workspace with assignment and student tracking', 'school'],
                            ['seller', 'Seller / Vendor', 'Merchant catalog, inventory, and sales management', 'storefront'],
                            ['buyer', 'Customer / Shopper', 'Product catalog, shopping cart, and orders', 'shopping_bag'],
                            ['driver', 'Driver', 'Driver dispatch, rides, and route tracking', 'directions_car'],
                            ['rider', 'Rider / Passenger', 'Passenger ride booking and trip history', 'hail'],
                            ['partner', 'Partner', 'Partner integration and agency dashboard', 'handshake'],
                        ];

                        document.querySelectorAll('button, a[href]').forEach(el => {
                            const txt = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
                            for (const [rId, rLabel, rDesc, rIcon] of roleMatches) {
                                if (
                                    txt === `sign in as ${rId}` ||
                                    txt === `login as ${rId}` ||
                                    txt === `log in as ${rId}` ||
                                    txt === `${rId} login` ||
                                    txt === `${rId} portal` ||
                                    txt === `${rId} sign in`
                                ) {
                                    detected.push({
                                        id: rId,
                                        label: `${rLabel} Portal`,
                                        description: rDesc,
                                        icon: rIcon,
                                        source: 'portal_button'
                                    });
                                }
                            }
                        });

                        return detected;
                    }
                """)
                for r in dom_roles:
                    if r["id"] not in roles_by_id:
                        roles_by_id[r["id"]] = r
            except Exception as e:
                logger.debug("DOM role inspection encountered: %s", e)

        # 2. Inspect discovered links for multiple candidate application namespaces (/admin, /app, etc.)
        try:
            current_url = getattr(page, "url", self.url) if page else self.url
            base_parsed = urlparse(current_url)
            page_links = await self._extract_page_links(page, base_parsed) if page else []
            paths = [l.get("path", "").lower() for l in page_links if l.get("path")]

            namespace_catalog = {
                "admin": {
                    "prefixes": ("/admin", "/administrator", "/console", "/manage"),
                    "label": "Admin Console (/admin)",
                    "description": "System administration, user access control, and settings",
                    "icon": "admin_panel_settings",
                },
                "app": {
                    "prefixes": ("/app", "/dashboard", "/workspace", "/portal"),
                    "label": "Application Workspace (/app)",
                    "description": "Main application dashboard and product workflows",
                    "icon": "dashboard",
                },
                "seller": {
                    "prefixes": ("/seller", "/vendor", "/merchant", "/supplier"),
                    "label": "Seller Portal (/seller)",
                    "description": "Inventory listings, orders, and storefront management",
                    "icon": "storefront",
                },
                "buyer": {
                    "prefixes": ("/shop", "/store", "/products", "/marketplace", "/catalog"),
                    "label": "Customer Storefront",
                    "description": "Product browsing, cart, and consumer purchasing",
                    "icon": "shopping_bag",
                },
                "instructor": {
                    "prefixes": ("/instructor", "/teacher", "/educator"),
                    "label": "Instructor Workspace",
                    "description": "Course creation, curriculum management, and grading",
                    "icon": "school",
                },
                "student": {
                    "prefixes": ("/student", "/learn", "/courses"),
                    "label": "Student Learning Workspace",
                    "description": "Course access, lessons, and assignments",
                    "icon": "menu_book",
                },
                "developer": {
                    "prefixes": ("/developer", "/dev", "/docs", "/api"),
                    "label": "Developer Platform (/docs)",
                    "description": "API references, SDK documentation, and developer tools",
                    "icon": "code",
                },
            }

            for ns_id, ns_info in namespace_catalog.items():
                if any(any(p.startswith(pref) for pref in ns_info["prefixes"]) for p in paths):
                    if ns_id not in roles_by_id:
                        roles_by_id[ns_id] = {
                            "id": ns_id,
                            "label": ns_info["label"],
                            "description": ns_info["description"],
                            "icon": ns_info["icon"],
                            "source": "route_namespace",
                        }
        except Exception as e:
            logger.debug("Namespace inspection encountered: %s", e)

        # Only present role selection question if there are 2 or more distinct roles/workspaces
        if len(roles_by_id) >= 2:
            options = list(roles_by_id.values())
            # Add public visitor option so the user can choose to explore the public site
            options.append({
                "id": "visitor",
                "label": "Public Surface",
                "description": "Explore the public landing page, general features, and visitor journeys",
                "icon": "public",
                "source": "fallback",
            })
            return options

        return []

    async def _analyze_routes(self, page, base_url: str, selected_role: str | None = None) -> list[dict]:
        """Bounded exploration: build an application map.

        Strategy:
        1. Try sitemap.xml first (fast, comprehensive)
        2. Scan page DOM for links (a[href], nav, buttons)
        3. Prioritize by keywords and selected role (elevating chosen role/workspace)
        4. Detect auth boundaries
        5. Cap at 10 routes probed in parallel via API request

        Returns list of route dicts with accessibility info.
        """
        route_map = []
        seen_paths = set()
        base_parsed = urlparse(base_url)

        # Step 1: Try sitemap.xml
        sitemap_routes = await self._try_sitemap(page, base_url, base_parsed)
        for route in sitemap_routes:
            if route["path"] not in seen_paths:
                seen_paths.add(route["path"])
                route_map.append(route)

        logger.info("Sitemap provided %d routes", len(sitemap_routes))

        # Step 2: Scan current page DOM for links and interactive action buttons
        page_links = await self._extract_page_links(page, base_parsed)
        for link in page_links:
            if link["path"] not in seen_paths:
                seen_paths.add(link["path"])
                route_map.append({
                    "path": link["path"],
                    "url": link["url"],
                    "text": link["text"],
                    "source": "button" if link.get("is_button") else "dom",
                    "accessible": True if link.get("is_button") else False,
                    "status": 200 if link.get("is_button") else None,
                    "title": link["text"] if link.get("is_button") else None,
                    "elements_count": 5 if link.get("is_button") else 0,
                    "has_form": False,
                    "category": "feature" if link.get("is_button") else "navigation",
                    "is_button": link.get("is_button", False),
                    "selector": link.get("selector", ""),
                    "error": None,
                })

        logger.info("DOM scan found %d additional routes/buttons", len(page_links))

        # Step 3: Prioritize by keywords and selected role
        prioritized = self._prioritize_routes(route_map, selected_role=selected_role)

        # Step 4: Probe top routes via API request (exclude DOM buttons from HTTP probe)
        network_targets = [r for r in prioritized if not r.get("is_button")][:6]
        button_targets = [r for r in prioritized if r.get("is_button")][:8]
        if network_targets:
            results = await asyncio.gather(
                *(self._probe_route(page, route) for route in network_targets),
                return_exceptions=True,
            )
            analyzed = [r for r in results if isinstance(r, dict)] + button_targets
        else:
            analyzed = list(button_targets)

        # Step 5: Detect auth boundaries
        auth_routes = [r for r in analyzed if r.get("category") == "auth"]
        if auth_routes:
            logger.info("Detected %d auth routes: %s", len(auth_routes), [r["path"] for r in auth_routes])

        return analyzed

    async def _try_sitemap(self, page, base_url: str, base_parsed) -> list[dict]:
        """Try to fetch and parse sitemap.xml for fast route discovery."""
        sitemap_routes = []
        sitemap_url = f"{base_parsed.scheme}://{base_parsed.netloc}/sitemap.xml"

        try:
            response = await page.request.get(sitemap_url, timeout=800, fail_on_status_code=False)
            if response.status >= 400:
                return sitemap_routes

            content = await response.text()
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(content)
                # Handle standard sitemap format
                ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                urls = root.findall(".//sm:url/sm:loc", ns) or root.findall(".//url/loc")
                for loc in urls[:30]:  # Cap at 30
                    url = loc.text
                    if url and base_parsed.netloc in url:
                        parsed = urlparse(url)
                        path = parsed.path
                        if path and path != "/":
                            sitemap_routes.append({
                                "path": path,
                                "url": url,
                                "text": path.split("/")[-1].replace("-", " ").title(),
                                "source": "sitemap",
                                "accessible": False,
                                "status": None,
                                "title": None,
                                "elements_count": 0,
                                "has_form": False,
                                "category": "navigation",
                                "error": None,
                            })
            except ET.ParseError:
                pass
        except Exception as e:
            logger.debug("Sitemap fetch failed: %s", e)

        return sitemap_routes

    async def _extract_page_links(self, page, base_parsed) -> list[dict]:
        """Extract all internal links and SPA navigation anchors from current page DOM."""
        links = []

        extract_js = """
        () => {
            const results = [];
            // 1. Navigation links and router elements with href/data-href/data-to
            const linkSelector = 'a[href], [role="link"][data-href], [role="link"][href], button[data-href], button[data-to], [role="menuitem"][data-href]';
            const linkNodes = document.querySelectorAll(linkSelector);
            for (const n of linkNodes) {
                const href = n.getAttribute('href') || n.getAttribute('data-href') || n.getAttribute('data-to') || '';
                const text = (n.innerText || n.getAttribute('aria-label') || n.getAttribute('title') || '').trim();
                if (!href || href === '#' || href.startsWith('javascript:')) continue;
                results.push({href, text, is_button: false});
            }

            // 2. Visible action buttons and controls (SPAs with modal/workflow triggers)
            const btnSelector = 'button:not([type="submit"]), [role="button"], a.btn, a[class*="button" i]';
            const btnNodes = document.querySelectorAll(btnSelector);
            for (const b of btnNodes) {
                const rect = b.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const style = window.getComputedStyle(b);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                const text = (b.innerText || b.getAttribute('aria-label') || b.getAttribute('title') || '').trim();
                if (!text || text.length < 3 || text.length > 50) continue;
                const tLower = text.toLowerCase();
                if (['close', 'cancel', 'ok', 'yes', 'no', 'menu', 'toggle', 'sign in', 'sign up', 'login', 'signup'].includes(tLower)) continue;
                results.push({
                    href: '',
                    text: text,
                    is_button: true,
                    tagName: b.tagName.toLowerCase(),
                    id: b.id || '',
                });
            }
            return results;
        }
        """
        try:
            raw_links = await page.evaluate(extract_js)
        except Exception:
            raw_links = []

        seen = set()
        for link in raw_links:
            if not isinstance(link, dict):
                continue
            text = (link.get("text") or "").strip()
            is_button = link.get("is_button", False)

            if is_button:
                if not text:
                    continue
                clean_slug = re.sub(r'[^a-zA-Z0-9]+', '-', text.lower()).strip('-')
                path = f"#action/{clean_slug}"
                if path in seen:
                    continue
                seen.add(path)
                tag_name = link.get("tagName", "button")
                safe_text = text.replace('"', '\\"').replace("'", "\\'")
                selector = f"{tag_name}:has-text('{safe_text}')"
                links.append({
                    "path": path,
                    "url": f"{base_parsed.scheme}://{base_parsed.netloc}{path}",
                    "text": text,
                    "is_button": True,
                    "selector": selector,
                })
                continue

            href = link.get("href") or ""
            if not href or href == "/":
                continue

            # Support hash-based SPA sections (e.g. /#explore, #quizzes)
            if href.startswith("/#") or (href.startswith("#") and len(href) > 2):
                clean_hash = href if href.startswith("/") else f"/{href}"
                path = clean_hash
                full_url = f"{base_parsed.scheme}://{base_parsed.netloc}{clean_hash}"
            elif href.startswith("/"):
                path = href
                full_url = f"{base_parsed.scheme}://{base_parsed.netloc}{href}"
            elif base_parsed.netloc in href:
                parsed = urlparse(href)
                path = parsed.path + (f"#{parsed.fragment}" if parsed.fragment else "")
                full_url = href
            else:
                continue

            if path in seen or path == "/":
                continue
            seen.add(path)

            links.append({
                "path": path,
                "url": full_url,
                "text": text if isinstance(text, str) else "",
                "is_button": False,
            })

        return links

    def _prioritize_routes(self, routes: list[dict], selected_role: str | None = None) -> list[dict]:
        """Prioritize routes by feature importance, elevating core workflows and selected workspace over auth."""
        priority_map = {
            # Highest priority: Dashboards and core application workspaces
            "dashboard": 0,
            "workspace": 0,
            "app": 0,
            "portal": 0,
            "console": 0,
            # Core feature actions and CRUD workflows
            "create": 1,
            "new": 1,
            "manage": 1,
            "project": 1,
            "repo": 1,
            "code": 1,
            "api": 1,
            "docs": 1,
            "quiz": 1,
            "study": 1,
            "exam": 1,
            "test": 1,
            "flashcard": 1,
            "card": 1,
            "deck": 1,
            "learn": 1,
            "practice": 1,
            "review": 1,
            "generate": 1,
            "generator": 1,
            "edit": 1,
            "course": 1,
            "document": 1,
            "note": 1,
            "upload": 1,
            "analytics": 1,
            # Content discovery and library
            "explore": 2,
            "library": 2,
            "search": 2,
            "browse": 2,
            "collection": 2,
            "material": 2,
            "resource": 2,
            "discover": 2,
            # Settings and configurations (deprioritized below core features)
            "settings": 3,
            "profile": 3,
            "preference": 3,
            "account": 3,
            "admin": 3,
            # Standalone forms
            "contact": 4,
            "feedback": 4,
            "form": 4,
            "support": 4,
            # Auth routes (checked for boundary detection, but de-emphasized vs real features)
            "auth": 5,
            "login": 5,
            "signin": 5,
            "signup": 5,
            "register": 5,
        }

        def get_priority(route: dict) -> int:
            path_lower = route["path"].lower()
            text_lower = (route.get("text") or "").lower()
            combined = f"{path_lower} {text_lower}"
            if selected_role and selected_role.lower() != "visitor":
                r_clean = selected_role.lower()
                if f"/{r_clean}" in path_lower or r_clean in text_lower:
                    return -1
            for kw, priority in priority_map.items():
                if kw in combined:
                    return priority
            return 6  # Default low priority for generic links

        return sorted(routes, key=get_priority)

    async def _probe_route(self, page, route: dict) -> dict:
        """Probe a route via API request (no navigation)."""
        route_info = route.copy()

        try:
            response = await page.request.get(
                route["url"], timeout=1200, fail_on_status_code=False
            )
            route_info["status"] = response.status
            route_info["accessible"] = 200 <= response.status < 400

            final_url = getattr(response, "url", route["url"])
            from app.engine.browser.auth import is_auth_url
            if (is_auth_url(final_url) and not is_auth_url(route["url"])) or response.status in (401, 403):
                route_info["requires_auth"] = True
                if is_auth_url(final_url):
                    route_info["auth_redirect_url"] = final_url

            if route_info["accessible"]:
                try:
                    body = await response.text()
                    title_match = re.search(
                        r"<title[^>]*>(.*?)</title>", body, re.I | re.S
                    )
                    if title_match:
                        route_info["title"] = title_match.group(1).strip()
                    route_info["elements_count"] = len(
                        re.findall(
                            r"<(?:input|button|select|textarea)\b|<a\s[^>]*href",
                            body,
                            re.I,
                        )
                    )
                    route_info["has_form"] = "<form" in body.lower()
                except Exception:
                    pass

            route_info["category"] = self._categorize_route(
                route["path"], route_info.get("title")
            )
        except Exception as e:
            route_info["error"] = str(e)[:100]
            route_info["accessible"] = False

        return route_info

    def _categorize_route(self, path: str, title: str | None) -> str:
        """Categorize a route based on path and title."""
        path_lower = path.lower()
        title_lower = (title or "").lower()

        # Auth routes — strictly identified by actual path endpoint, not redirected title
        auth_path_patterns = [
            r"/sign-?in\b", r"/log-?in\b", r"/sign-?up\b", r"/register\b",
            r"/auth\b", r"/session\b", r"/account/login\b", r"/accounts/login\b",
            r"/user/login\b", r"/app/login\b",
        ]
        if any(re.search(pat, path_lower) for pat in auth_path_patterns):
            return "auth"

        # Standalone form routes (contact, feedback, support, inquiry, etc.)
        form_keywords = ["contact", "feedback", "support", "inquiry", "message", "help/contact"]
        if any(kw in path_lower for kw in form_keywords) or (title and any(kw in title_lower for kw in form_keywords)):
            return "form"

        # Feature routes (dashboard, workspace, quiz, study, creation, tools, settings, etc.)
        feature_keywords = [
            "quiz", "study", "exam", "test", "flashcard", "card", "deck",
            "course", "learn", "practice", "review", "question",
            "dashboard", "workspace", "app", "portal", "console",
            "create", "new", "edit", "manage", "builder", "generator", "generate",
            "project", "document", "note", "upload", "file", "analytics",
            "settings", "profile", "account", "preference", "admin",
        ]
        if any(kw in path_lower for kw in feature_keywords) or (title and any(kw in title_lower for kw in feature_keywords)):
            return "feature"

        # Content routes (browse, search, explore, library, resources, etc.)
        content_keywords = [
            "explore", "search", "browse", "library", "catalog", "collection",
            "material", "resource", "community", "public", "topic", "subject",
            "tag", "category", "feed", "discover",
        ]
        if any(kw in path_lower for kw in content_keywords) or (title and any(kw in title_lower for kw in content_keywords)):
            return "content"

        return "navigation"

    def _detect_personas(self, route_map: list[dict]) -> list[str]:
        """Auto-detect relevant auditing personas based on route analysis."""
        personas = []
        categories = {r["category"] for r in route_map}
        paths = {r["path"].lower() for r in route_map}

        # Developer / Engineering platforms (GitHub, GitLab, developer tools, API docs)
        dev_indicators = [
            "/features/code", "/apps/", "/pulls", "/issues", "/commit",
            "/docs", "/api", "/sdk", "/developer", "repository", "copilot", "desktop"
        ]
        if any(any(ind in p for ind in dev_indicators) for p in paths):
            personas.append("developer")
            personas.append("visitor")

        # SaaS / App personas
        if "auth" in categories:
            if any("dashboard" in p or "home" in p for p in paths):
                personas.append("user")
            if any("admin" in p or "settings" in p for p in paths):
                personas.append("admin")

        # E-commerce personas
        if any("cart" in p or "checkout" in p for p in paths):
            personas.append("shopper")
        if any("seller" in p or "vendor" in p or "merchant" in p for p in paths):
            personas.append("seller")

        # Tool / Workspace personas
        if any("project" in p or "workspace" in p for p in paths):
            personas.append("member")

        # Default to user / visitor if no specific personas detected
        if not personas:
            personas.append("visitor")
            personas.append("user")

        return personas

    async def _discover_workflows(
        self,
        page,
        observation: dict,
        selected_role: str | None,
    ) -> tuple[list[DiscoveryItem], list[DiscoveredMission]]:
        """Analyze routes and generate meaningful persona-based missions.

        Phase 1: Analyze all internal links for accessibility and categorization
        Phase 2: Auto-detect relevant personas
        Phase 3: Generate multi-step journeys with real purpose
        """
        elements = observation.get("elements", [])
        title = observation.get("title", "")
        current_url = getattr(page, "url", self.url)

        # Require minimum evidence before generating any missions
        real_interactive_count = sum(
            1 for el in elements
            if el.get("name") and len(el.get("name", "").strip()) >= 3
        )
        if real_interactive_count < 2:
            return [], []

        discovered_areas: list[DiscoveryItem] = []
        missions: list[DiscoveredMission] = []

        # Phase 1: Route analysis
        route_map = await self._analyze_routes(page, current_url, selected_role=selected_role)
        accessible_routes = [r for r in route_map if r["accessible"]]
        auth_routes = [r for r in route_map if r["category"] == "auth"]
        form_routes = [
            r for r in route_map
            if (r.get("accessible") or r.get("requires_auth"))
            and (
                r["category"] == "form"
                or (
                    r.get("has_form")
                    and any(
                        kw in r["path"].lower() or kw in (r.get("title") or "").lower()
                        for kw in ["contact", "feedback", "support", "inquiry", "message"]
                    )
                )
            )
        ]
        feature_routes = [
            r for r in route_map
            if (r.get("accessible") or r.get("requires_auth")) and r.get("category") == "feature"
        ]
        content_routes = [
            r for r in route_map
            if (r.get("accessible") or r.get("requires_auth")) and r.get("category") == "content"
        ]
        blocked_routes = [r for r in route_map if not r["accessible"] and not r.get("requires_auth")]

        signup_routes = [
            r for r in route_map
            if (r.get("accessible") or r.get("requires_auth"))
            and any(
                kw in r["path"].lower() or kw in (r.get("title") or "").lower()
                for kw in ["signup", "sign-up", "register", "create-account", "join"]
            )
        ]
        login_routes = [
            r for r in route_map
            if (r.get("accessible") or r.get("requires_auth"))
            and any(
                kw in r["path"].lower() or kw in (r.get("title") or "").lower()
                for kw in ["login", "log-in", "signin", "sign-in"]
            )
        ]

        # Add route analysis to discoveries
        if route_map:
            discovered_areas.append(
                DiscoveryItem(
                    label="Route Analysis Complete",
                    description=f"Found {len(accessible_routes)} accessible routes, {len(auth_routes)} require auth, {len(blocked_routes)} blocked",
                )
            )
        for r in accessible_routes[:4]:
            discovered_areas.append(
                DiscoveryItem(
                    label=r["text"] or r["path"],
                    description=f"[{r['category'].upper()}] {r['path']} — {r['elements_count']} elements",
                )
            )

        # Phase 2: Persona detection
        detected_personas = self._detect_personas(route_map)
        persona_name = selected_role.capitalize() if selected_role else (detected_personas[0].capitalize() if detected_personas else "Visitor")
        persona_evidence = (
            f"Selected workspace ({selected_role})"
            if selected_role
            else ("Grounded from developer platform routes" if any("developer" in p for p in detected_personas) else "Public visitor perspective")
        )
        logger.info("Detected personas: %s, using: %s (%s)", detected_personas, persona_name, persona_evidence)

        # Collect interactive elements for fallback
        seen_labels: set[str] = set()
        interactive_elements: list[dict] = []
        for el in elements:
            name = el.get("name", "").strip()
            if not name or len(name) < 3 or len(name) > 60:
                continue
            if name.lower() in {"sign out", "logout", "close", "cancel", "ok", "yes", "no", "back"}:
                continue
            if name.lower() not in seen_labels:
                seen_labels.add(name.lower())
                interactive_elements.append(el)

        # Cache discovery state for fast DiscoveryResult synthesis
        self._last_route_map = route_map
        self._last_interactive_elements = interactive_elements
        self._last_persona = persona_name

        # Surface observed interactive elements as discoveries even when route
        # analysis finds nothing (unit tests / SPA shells without crawlable links)
        if not route_map and interactive_elements:
            discovered_areas.append(
                DiscoveryItem(
                    label="Interactive surface detected",
                    description=f"Found {len(interactive_elements)} interactive controls on {title or current_url}",
                )
            )
            for el in interactive_elements[:4]:
                discovered_areas.append(
                    DiscoveryItem(
                        label=el.get("name", "").strip(),
                        description=f"Control: {el.get('type', 'element')} — candidate journey entry",
                    )
                )

        # Phase 3: Generate intelligent user journeys (AI-synthesized feature journeys first)
        mission_count = 0
        max_missions = 6

        # Step 3a: Goal-directed mission (highest priority when explicitly requested by user)
        if self.goal and mission_count < max_missions:
            goal_missions = await self._build_goal_mission(
                self.goal, current_url, title, persona_name, interactive_elements, project_id=self.project_id
            )
            if goal_missions:
                for gm in goal_missions:
                    if mission_count >= max_missions:
                        break
                    gm.persona_evidence = persona_evidence
                    missions.append(gm)
                    mission_count += 1

        # Step 3b: Attempt AI-powered journey synthesis for feature discovery
        ai_provider = get_ai_provider()
        ai_reasoner = AgentReasoner(ai_provider) if ai_provider else None

        if ai_reasoner and (route_map or interactive_elements) and mission_count < max_missions:
            try:
                # Prune and compact page summary tokens to keep LLM response fast
                page_text = (
                    (observation.get("text") or "")[:400]
                    + " "
                    + " ".join([el.get("name", "") for el in interactive_elements[:15] if el.get("name")])
                ).strip()
                ai_journeys_result = await asyncio.wait_for(
                    ai_reasoner.synthesize_journeys(
                        base_url=current_url,
                        title=title,
                        goal=self.goal,
                        persona=persona_name,
                        routes=route_map[:8],
                        interactive_elements=interactive_elements[:15],
                        page_summary=page_text,
                        max_journeys=max_missions - mission_count,
                    ),
                    timeout=10.0,
                )
                if ai_journeys_result and ai_journeys_result.journeys:
                    self._ai_recommendation_reason = ai_journeys_result.recommendation_reason
                    has_recommended = any(m.recommended for m in missions)
                    for j in ai_journeys_result.journeys:
                        is_rec = j.recommended and not has_recommended
                        # Never recommend an auth or settings journey if there are other feature journeys
                        if is_rec and j.category in ("auth", "settings") and len(ai_journeys_result.journeys) > 1:
                            is_rec = False
                        if is_rec:
                            has_recommended = True

                        missions.append(
                            DiscoveredMission(
                                id=f"mission-{uuid.uuid4().hex[:8]}",
                                name=j.name,
                                title=j.title,
                                description=j.description,
                                objective=j.objective,
                                persona=j.persona or persona_name,
                                persona_evidence=persona_evidence,
                                category=j.category,
                                journey=j.journey,
                                steps=j.steps,
                                successCondition=j.success_condition or None,
                                confidence=j.confidence,
                                recommended=is_rec,
                                estimated_time_seconds=j.estimated_time_seconds,
                                expectation_source="ai_synthesized",
                                review_required=True,
                            )
                        )
                    if not has_recommended and missions:
                        first_core_feature = next((m for m in missions if m.category not in ("auth", "settings")), None)
                        target = first_core_feature or next((m for m in missions if m.category != "auth"), missions[0])
                        target.recommended = True
                    mission_count = len(missions)
            except asyncio.TimeoutError:
                logger.warning("AI journey synthesis timed out after 25s, falling back to heuristics")
            except Exception as e:
                err_msg = str(e) or type(e).__name__
                logger.warning("AI journey synthesis failed, falling back to heuristics: %s", err_msg)

        # Step 3c: Heuristic route-based journeys (if AI did not produce missions)
        if len(missions) <= (1 if self.goal else 0):

            # Feature journeys (genuine product workflows prioritized over settings/profile)
            genuine_features = [
                r for r in feature_routes
                if not any(sk in r["path"].lower() for sk in ["settings", "profile", "account", "preference"])
            ]
            utility_features = [
                r for r in feature_routes
                if any(sk in r["path"].lower() for sk in ["settings", "profile", "account", "preference"])
            ]
            ordered_features = genuine_features + utility_features

            all_caps: list[Any] = []
            if self.project_id and self._db_session:
                try:
                    from app.modules.product_graph.repository import ProductGraphRepository
                    pg_repo = ProductGraphRepository(self._db_session)
                    all_caps = await pg_repo.list_capabilities_by_project(self.project_id)
                except Exception:
                    pass

            for route in ordered_features[:4]:
                if mission_count >= max_missions:
                    break
                if all_caps:
                    cap = self._find_capability_for_route(route, all_caps)
                    if not cap:
                        continue
                is_settings = any(sk in route["path"].lower() for sk in ["settings", "profile", "account", "preference"])
                is_first = (mission_count == 0 and not self.goal and not is_settings)
                feature_mission = self._build_feature_mission(
                    route, current_url, title, persona_name, recommended=is_first
                )
                if feature_mission:
                    missions.append(feature_mission)
                    mission_count += 1

            # Content journeys (explore, search, catalog, library)
            for route in content_routes[:2]:
                if mission_count >= max_missions:
                    break
                has_rec = any(m.recommended for m in missions)
                is_first = (not has_rec and not self.goal)
                content_mission = self._build_content_mission(
                    route, current_url, title, persona_name, recommended=is_first
                )
                if content_mission:
                    missions.append(content_mission)
                    mission_count += 1

            # Standalone form journeys (contact, feedback, etc.)
            for route in form_routes[:2]:
                if mission_count >= max_missions:
                    break
                form_mission = self._build_standalone_form_mission(
                    route, current_url, title, persona_name
                )
                if form_mission:
                    missions.append(form_mission)
                    mission_count += 1

            # Chained auth journey (secondary setup flow, never prioritized over features)
            if signup_routes and login_routes and mission_count < max_missions:
                chained_auth_mission = await self._build_chained_auth_mission(
                    signup_routes[0],
                    login_routes[0],
                    current_url,
                    title,
                    persona_name,
                    credential_id=self.credential_id,
                )
                if chained_auth_mission:
                    missions.append(chained_auth_mission)
                    mission_count += 1

            # Auth journey (secondary setup flow)
            if auth_routes and not (signup_routes and login_routes) and mission_count < max_missions:
                auth_route = auth_routes[0]
                auth_mission = self._build_auth_mission(
                    auth_route, current_url, title, persona_name,
                    credential_id=self.credential_id,
                )
                if auth_mission:
                    missions.append(auth_mission)
                    mission_count += 1

        # Complement with element-based missions if route analysis yielded few candidates
        if len(missions) < 4 and interactive_elements:
            # Check for contact form controls on current page if not already present
            has_form_mission = any(m.category == "form" for m in missions)
            has_contact = any(
                "contact" in el.get("name", "").lower()
                or "message" in el.get("name", "").lower()
                or el.get("type") == "textarea"
                for el in interactive_elements
            )
            if not has_form_mission and has_contact and mission_count < max_missions:
                current_page_form_route = {
                    "path": urlparse(current_url).path or "/contact",
                    "url": current_url,
                    "title": title or "Contact",
                    "text": "Contact",
                    "category": "form",
                    "has_form": True,
                }
                form_mission = self._build_standalone_form_mission(
                    current_page_form_route, current_url, title, persona_name
                )
                if form_mission:
                    missions.append(form_mission)
                    mission_count += 1

            existing_names = {m.name.lower() for m in missions}
            for el in interactive_elements:
                if mission_count >= max_missions:
                    break
                el_name = el.get("name", "").strip()
                if not el_name or any(el_name.lower() in en or en in el_name.lower() for en in existing_names):
                    continue
                has_rec = any(m.recommended for m in missions)
                mission = self._build_element_mission(
                    el, current_url, title, persona_name,
                    recommended=(not has_rec and not self.goal)
                )
                if mission:
                    missions.append(mission)
                    existing_names.add(mission.name.lower())
                    mission_count += 1

        # If no missions were generated from routes or controls (e.g. SPAs, portfolios, single-page sites),
        # synthesize robust structure-based journeys so the exploration always produces actionable flows
        if len(missions) == 0:
            fallback_missions = await self._synthesize_fallback_missions(
                page, current_url, title, persona_name, observation
            )
            missions.extend(fallback_missions)
            if not discovered_areas:
                discovered_areas.append(
                    DiscoveryItem(
                        label="Application Interface Mapped",
                        description=f"Mapped landing sections, interactive controls, and key workflows on {title or current_url}",
                    )
                )

        # Ensure at least one high-value candidate is recommended if none currently is
        if not any(m.recommended for m in missions) and missions and not self.goal:
            fav = next(
                (
                    m for m in missions
                    if m.category not in ("auth", "settings")
                    and not any(sk in m.name.lower() for sk in ["setting", "profile", "account", "preference", "sign up", "log in", "auth"])
                ),
                None,
            )
            if fav:
                fav.recommended = True
            else:
                non_auth = next((m for m in missions if m.category != "auth"), None)
                if non_auth:
                    non_auth.recommended = True

        # Sort: recommended non-auth first, then by priority category (features/dashboards before auth)
        category_order = {
            "feature": 0, "dashboard": 1, "content": 2, "workflow": 3,
            "crud": 4, "form": 5, "auth": 6, "navigation": 7
        }
        missions.sort(key=lambda m: (
            0 if (self.goal and (m.name == self.goal or m.title == self.goal)) else (0 if (m.recommended and m.category != "auth") else 1),
            category_order.get(m.category or "navigation", 9)
        ))

        # Stable IDs and visible uncertainty make discovery records reproducible
        # across equivalent exploration passes. Route/control evidence is kept
        # separate from expected behavior because those expectations are inferred.
        unique: list[DiscoveredMission] = []
        seen_candidates: set[tuple[str, str, str]] = set()
        for mission in missions:
            # Generated actions already use locator auto-waiting and navigation
            # uses DOM readiness. Fixed sleeps add latency and make replay less
            # reliable, so keep generated candidates state-driven.
            mission.steps = [
                step for step in mission.steps
                if not isinstance(step, dict)
                or str(step.get("type") or step.get("action") or "").lower() != "wait"
            ]
            evidence_key = (mission.category or "", mission.name.strip().casefold(), (mission.route_analysis or {}).get("path", ""))
            if evidence_key in seen_candidates:
                continue
            seen_candidates.add(evidence_key)
            stable_key = f"{current_url}|{evidence_key[0]}|{evidence_key[1]}|{evidence_key[2]}"
            mission.id = f"mission-{uuid.uuid5(uuid.NAMESPACE_URL, stable_key).hex[:16]}"
            for step_index, step in enumerate(mission.steps, start=1):
                if isinstance(step, dict):
                    step.setdefault("step_id", f"{mission.id}-step-{step_index}")
            mission.expectation_source = "inferred" if mission.successCondition else "unspecified"
            mission.review_required = mission.expectation_source != "observed"
            mission.discovery_evidence = [{"kind": "page", "url": current_url, "title": title}]
            if mission.route_analysis:
                mission.discovery_evidence.append({
                    "kind": "route", "path": mission.route_analysis.get("path"),
                    "accessible": mission.route_analysis.get("accessible"),
                })
            else:
                mission.discovery_evidence.extend({
                    "kind": "interactive_control", "label": el.get("name"), "type": el.get("type")
                } for el in interactive_elements[:3])
            unique.append(mission)

        return discovered_areas, unique

    async def _synthesize_fallback_missions(
        self,
        page,
        base_url: str,
        title: str,
        persona: str,
        observation: dict,
    ) -> list[DiscoveredMission]:
        """Synthesize guaranteed high-quality candidate journeys for any reachable web application or portfolio."""
        title_clean = (title or "").strip() or urlparse(base_url).hostname or "Application"
        is_portfolio = any(
            kw in title_clean.lower() or kw in base_url.lower()
            for kw in ["portfolio", "engineer", "developer", "designer", "creator"]
        )

        missions: list[DiscoveredMission] = []

        if is_portfolio:
            missions.append(
                DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name="Explore Project Showcase & Works",
                    title="Explore Project Showcase & Works",
                    description=f"Explore featured projects, digital products, and architectural work on {title_clean}.",
                    objective="Verify that featured projects, interactive cards, and demo links load and navigate cleanly",
                    persona=persona,
                    category="feature",
                    journey=[
                        f"Open {title_clean}",
                        "Scroll through showcased projects and technical demonstrations",
                        "Verify project cards, demo buttons, and case studies render interactively",
                    ],
                    steps=[
                        {"type": "navigate", "url": base_url},
                        {"type": "scroll", "direction": "down", "amount": 800},
                        {"type": "assert_visible", "target": {"css": "a, button, [role='button'], section"}},
                    ],
                    successCondition={"element_count": {"selector": "a, button, article, [role='article']", "min": 2}},
                    confidence=0.88,
                    recommended=True,
                    estimated_time_seconds=15,
                )
            )
            missions.append(
                DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name="Inspect Technical Stack & Skills Overview",
                    title="Inspect Technical Stack & Skills Overview",
                    description=f"Review developer competencies, technologies, and experience sections on {title_clean}.",
                    objective="Ensure skills matrix, engineering domains, and background sections are visible without errors",
                    persona=persona,
                    category="content",
                    journey=[
                        f"Open {title_clean}",
                        "Scroll through experience, technologies, and technical skills",
                        "Verify skill tags, badges, and background content are clearly visible",
                    ],
                    steps=[
                        {"type": "navigate", "url": base_url},
                        {"type": "scroll", "direction": "down", "amount": 1200},
                        {"type": "assert_visible", "target": {"css": "section, div, main"}},
                    ],
                    successCondition={"element_count": {"selector": "div, section, p", "min": 3}},
                    confidence=0.82,
                    recommended=False,
                    estimated_time_seconds=12,
                )
            )
            missions.append(
                DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name="Initiate Contact / Collaboration Workflow",
                    title="Initiate Contact / Collaboration Workflow",
                    description=f"Locate contact channels, inquiry links, or message form on {title_clean}.",
                    objective="Verify that visitor can reach out via contact form or verified social / email channels",
                    persona=persona,
                    category="form",
                    journey=[
                        f"Open {title_clean}",
                        "Locate the contact or footer section",
                        "Verify contact methods, email links, or inquiry forms are interactive",
                    ],
                    steps=[
                        {"type": "navigate", "url": base_url},
                        {"type": "scroll", "direction": "down", "amount": 2000},
                    ],
                    successCondition={"element_count": {"selector": "a[href^='mailto:'], a[href*='github'], a[href*='linkedin'], a[href*='twitter'], a[href*='x.com'], button, form, input", "min": 1}},
                    confidence=0.85,
                    recommended=False,
                    estimated_time_seconds=10,
                )
            )
        else:
            missions.append(
                DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name="Explore Core Features & Navigation",
                    title="Explore Core Features & Navigation",
                    description=f"Navigate primary interface sections and interactive elements on {title_clean}.",
                    objective=f"Confirm that primary application views, navigation headers, and feature sections render correctly",
                    persona=persona,
                    category="feature",
                    journey=[
                        f"Open {title_clean}",
                        "Explore primary navigation and core feature sections",
                        "Confirm main interface and interactive controls respond as expected",
                    ],
                    steps=[
                        {"type": "navigate", "url": base_url},
                        {"type": "scroll", "direction": "down", "amount": 600},
                    ],
                    successCondition={"element_count": {"selector": "a, button, [role='button'], h1, h2, h3", "min": 2}},
                    confidence=0.85,
                    recommended=True,
                    estimated_time_seconds=15,
                )
            )
            missions.append(
                DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name="Inspect Layout & Responsive Structure",
                    title="Inspect Layout & Responsive Structure",
                    description=f"Verify visual integrity, responsive layout, and interactive affordances on {title_clean}.",
                    objective="Ensure full page loads without client runtime errors or broken layout containers",
                    persona=persona,
                    category="workflow",
                    journey=[
                        f"Open {title_clean}",
                        "Scroll through full page layout to inspect content flow",
                        "Verify header, body, and footer containers load completely",
                    ],
                    steps=[
                        {"type": "navigate", "url": base_url},
                        {"type": "scroll", "direction": "down", "amount": 1000},
                    ],
                    successCondition={"element_count": {"selector": "main, [role='main'], header, footer, body", "min": 1}},
                    confidence=0.80,
                    recommended=False,
                    estimated_time_seconds=12,
                )
            )

        return missions

    def _split_goal_into_criteria(self, goal: str) -> list[dict]:
        """Split a compound user goal into success criteria.

        Uses deterministic verb-noun matching first, then fallback patterns.
        """
        if not goal:
            return []

        patterns = [
            (["sign up", "signup", "register", "create account"], {"key": "signed_up", "value": True, "predicate": "eq"}),
            (["log in", "login", "sign in", "signin", "authenticate"], {"key": "authenticated", "value": True, "predicate": "eq"}),
            (["browse courses", "browse course", "browse", "view courses"], {"key": "courses_browsed", "value": True, "predicate": "eq"}),
            (["enroll", "join course", "take course"], {"key": "enrolled", "value": True, "predicate": "eq"}),
            (["complete quiz", "finish quiz", "take quiz", "quiz"], {"key": "quiz_completed", "value": True, "predicate": "eq"}),
            (["submit assignment", "turn in"], {"key": "assignment_submitted", "value": True, "predicate": "eq"}),
            (["view grade", "see result", "grades"], {"key": "grade_viewed", "value": True, "predicate": "eq"}),
            (["checkout", "purchase", "buy"], {"key": "purchase_completed", "value": True, "predicate": "eq"}),
        ]

        goal_lower = goal.lower()
        clauses = re.split(r"[,;]|\band\b|\bthen\b", goal_lower)
        criteria: list[dict] = []
        matched_keys: set[str] = set()

        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            for keywords, crit in patterns:
                if any(kw in clause for kw in keywords):
                    if crit["key"] not in matched_keys:
                        matched_keys.add(crit["key"])
                        criteria.append(dict(crit))
                    break

        if not criteria:
            for keywords, crit in patterns:
                if any(kw in goal_lower for kw in keywords):
                    if crit["key"] not in matched_keys:
                        matched_keys.add(crit["key"])
                        criteria.append(dict(crit))

        return criteria

    def _generate_fast_path_missions(
        self,
        page: Any,
        observation: dict[str, Any],
        goal: str | None,
    ) -> list[DiscoveredMission]:
        """Generate fast candidate missions immediately from initial DOM observation without waiting for deep AI or route crawling."""
        elements = observation.get("elements", [])
        title = observation.get("title", "")
        current_url = getattr(page, "url", self.url)
        missions: list[DiscoveredMission] = []

        # 1. Goal mission if provided
        if goal:
            goal_mission = self._build_route_walk_mission(
                goal=goal,
                base_url=current_url,
                title=title,
                persona="User",
                elements=elements,
            )
            goal_mission.recommended = True
            missions.append(goal_mission)

        # 2. Extract top 2-3 prominent interactive elements
        seen_names: set[str] = set()
        if goal:
            seen_names.add(goal.lower())

        priority_keywords = [
            "start", "get started", "explore", "sign up", "register", "login",
            "search", "new", "create", "pricing", "features", "dashboard",
            "docs", "documentation", "try", "demo"
        ]

        scored_elements: list[tuple[int, dict]] = []
        for el in elements:
            name = (el.get("name") or "").strip()
            if not name or len(name) < 3 or len(name) > 50:
                continue
            name_lower = name.lower()
            if name_lower in seen_names or name_lower in {"sign out", "logout", "close", "cancel", "ok", "yes", "no", "back"}:
                continue

            score = 0
            if el.get("type") in ("button", "a"):
                score += 2
            for kw in priority_keywords:
                if kw in name_lower:
                    score += 5
                    break
            scored_elements.append((score, el))

        scored_elements.sort(key=lambda x: x[0], reverse=True)

        for _, el in scored_elements[: (3 if not goal else 2)]:
            name = el["name"].strip()
            seen_names.add(name.lower())
            clean_name = name.replace("'", "\\'")
            selector = el.get("selector") or f"button:has-text('{clean_name}'), a:has-text('{clean_name}')"
            is_rec = len(missions) == 0

            missions.append(
                DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name=f"Explore {name}",
                    title=f"Explore {name}",
                    description=f"Interact with '{name}' on {title or 'application'} to test functionality.",
                    objective=f"Verify that interacting with '{name}' executes as expected.",
                    persona="User",
                    category="feature",
                    journey=[
                        f"Visit {title or 'application'}",
                        f"Click '{name}'",
                        "Verify visible feedback or navigation",
                    ],
                    steps=[
                        {"type": "navigate", "url": current_url},
                        {"type": "click", "target": selector},
                        {"type": "wait", "value": "500"},
                    ],
                    successCondition={"url_changed_to": {"from": current_url}},
                    confidence=0.85,
                    recommended=is_rec,
                    route_analysis={"accessible": True, "source": "fast_path"},
                    estimated_time_seconds=10,
                    expectation_source="fast_path",
                    review_required=False,
                )
            )

        return missions

    def _synthesize_fast_discovery_result(
        self,
        page_url: str,
        page_title: str,
        route_map: list[dict] | None = None,
        interactive_elements: list[dict] | None = None,
        persona_name: str | None = None,
    ) -> Any:
        """Construct a valid DiscoveryResult payload immediately from available route and DOM data."""
        from app.modules.product_graph.schemas import (
            Action,
            Capability,
            DiscoveryResult,
            Goal,
            Page,
            Persona,
        )

        pid = self.project_id or self.exploration_id
        if not pid:
            return None

        route_list = route_map or []
        elem_list = interactive_elements or []
        p_name = persona_name or "User"

        # Persona
        persona = Persona(
            project_id=pid,
            name=p_name,
            description=f"Standard {p_name} interacting with the application",
            confidence=0.9,
        )

        # Primary Page
        parsed = urlparse(page_url)
        path = parsed.path or "/"
        main_page = Page(
            project_id=pid,
            url_pattern=path,
            title=page_title or "Home",
            confidence=1.0,
        )
        pages = [main_page]

        # Additional pages from discovered routes
        seen_paths = {main_page.url_pattern}
        for r in route_list[:25]:
            r_path = r.get("path")
            if not r_path or r_path in seen_paths:
                continue
            seen_paths.add(r_path)
            pages.append(
                Page(
                    project_id=pid,
                    url_pattern=r_path,
                    title=r.get("title") or r.get("text") or r_path,
                    requires_auth=bool(r.get("requires_auth", False)),
                    confidence=0.85,
                )
            )

        # Actions on main page
        actions: list[Action] = []
        for el in elem_list[:20]:
            name = (el.get("name") or "").strip()
            if not name:
                continue
            clean_name = name.replace("'", "\\'")
            selector = el.get("selector") or f"text={clean_name}"
            actions.append(
                Action(
                    project_id=pid,
                    page_id=main_page.id,
                    name=f"Click {name[:50]}",
                    selector=selector,
                    action_type="click",
                    confidence=0.85,
                )
            )

        # Capabilities
        capabilities: list[Capability] = []
        for p in pages[:10]:
            clean_p = p.url_pattern.strip("/").replace("-", " ").replace("_", " ").title()
            cap_name = f"Access {clean_p or 'Home'}"
            capabilities.append(
                Capability(
                    project_id=pid,
                    name=cap_name,
                    description=f"Navigate to and access {p.url_pattern}",
                    kind="primary",
                    confidence=0.85,
                )
            )

        # Goals
        goals: list[Goal] = []
        if self.goal:
            goals.append(
                Goal(
                    project_id=pid,
                    name=self.goal,
                    description=f"User goal: {self.goal}",
                    persona_id=persona.id,
                    confidence=0.9,
                )
            )

        coverage = {p.url_pattern: "discovered" for p in pages}

        return DiscoveryResult(
            goals=goals,
            personas=[persona],
            pages=pages,
            actions=actions,
            capabilities=capabilities,
            coverage_map=coverage,
        )

    def _build_route_walk_mission(
        self, goal: str, base_url: str, title: str, persona: str, elements: list[dict],
    ) -> DiscoveredMission:
        """Fallback: emit a single route-walk mission with low confidence."""
        goal_words = [w.lower() for w in goal.split() if len(w) > 2]
        matching_el = next(
            (el for el in elements if any(gw in el.get("name", "").lower() for gw in goal_words)),
            None
        )
        el_name = matching_el.get("name") if matching_el else goal
        clean_name = el_name.replace("'", "\\'")
        target_selector = (
            f"button:has-text('{clean_name}'), a:has-text('{clean_name}'), [role='button']:has-text('{clean_name}')"
        )

        steps = [{"type": "navigate", "url": base_url}]
        steps.append({"type": "click", "target": target_selector})
        steps.append({"type": "wait", "value": "500"})

        is_matching = bool(matching_el)
        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=goal,
            title=goal,
            description=f"Attempt the goal '{goal}' and verify the application responds by changing state.",
            objective=f"Verify that {persona} can act on '{el_name}' and the application visibly responds" if is_matching else goal,
            persona=persona,
            category="feature" if is_matching else "route_walk",
            journey=[
                f"Access {title or 'application'}",
                f"Use the control matching the goal: '{el_name}'",
                "Verify the application state changes in response",
            ],
            steps=steps,
            successCondition={"url_changed_to": {"from": base_url}},
            confidence=0.75 if is_matching else 0.3,
            recommended=is_matching,
            route_analysis={
                "accessible": True,
                "source": "heuristic_fallback",
                "warning": "" if is_matching else "No matching capabilities found; emitted a route-walk mission. Consider running Product Discovery first.",
            },
            estimated_time_seconds=15,
        )

    def _find_capability_for_route(self, route: dict, all_capabilities: list[Any]) -> Any | None:
        """Find a capability from the Product Graph that corresponds to this route."""
        if not all_capabilities:
            return None
        path = (route.get("path") or "").lower()
        for cap in all_capabilities:
            cap_name = getattr(cap, "name", "").lower()
            cap_kind = getattr(cap, "kind", "").lower()
            if cap_kind == "auth" or "auth" in cap_name or "login" in cap_name:
                if any(ak in path for ak in ("login", "signin", "signup", "register", "auth")):
                    return cap
            clean_path = path.strip("/").replace("-", " ").replace("_", " ")
            if clean_path:
                path_words = [w for w in clean_path.split() if len(w) > 3]
                if any(w in cap_name for w in path_words):
                    return cap
                if clean_path in cap_name or cap_name in clean_path:
                    return cap
        return None

    async def _build_goal_mission(
        self, goal: str, base_url: str, title: str, persona: str, elements: list[dict],
        project_id: uuid.UUID | None = None,
    ) -> list[DiscoveredMission]:
        """Build one mission per feature in the goal. Falls back to a single
        route-walk mission if no criteria can be extracted or no capabilities match.
        """
        # 1. Split goal into success_criteria
        criteria = self._split_goal_into_criteria(goal)

        pid = project_id or self.project_id
        if not criteria or not pid or not self._db_session:
            return [self._build_route_walk_mission(goal, base_url, title, persona, elements)]

        try:
            from app.modules.product_graph.repository import ProductGraphRepository
            from app.modules.flows.service import FlowService

            pg_repo = ProductGraphRepository(self._db_session)
            goal_row = await pg_repo.create_goal(
                project_id=pid,
                name=goal,
                description=f"Discovered from exploration goal: {goal}",
                success_criteria=criteria,
                source="discovered",
            )

            flow_service = FlowService(self._db_session)
            generation_result = await flow_service.generate_flows(
                project_id=pid,
                goal_id=goal_row.id,
            )

            missions: list[DiscoveredMission] = []
            for flow in generation_result.flows:
                # Convert internal steps to runner dicts
                m_steps = [s.to_runner_dict() for s in flow.internal]
                journey_desc = [
                    s.description or f"{s.action} {s.target}"
                    for s in flow.internal
                ] or [f"Execute {flow.name}"]

                mission = DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    flow_id=getattr(flow, "id", None),
                    name=flow.name,
                    title=flow.name,
                    description=f"Generated feature flow for goal: {goal}",
                    objective=f"Verify capability workflow for {flow.name}",
                    persona=persona,
                    category="feature",
                    journey=journey_desc,
                    steps=m_steps,
                    successCondition=flow.state_contract.model_dump() if flow.state_contract else None,
                    confidence=max(flow.confidence, 0.85),
                    recommended=True,
                    route_analysis={"accessible": True, "source": "deterministic"},
                    estimated_time_seconds=15,
                )
                missions.append(mission)

            if not missions:
                return [self._build_route_walk_mission(goal, base_url, title, persona, elements)]

            return missions
        except Exception as e:
            logger.warning("Error generating feature flows from goal: %s", e)
            return [self._build_route_walk_mission(goal, base_url, title, persona, elements)]


    def _build_auth_mission(
        self, auth_route: dict, base_url: str, title: str, persona: str,
        credential_id: str | None = None,
    ) -> DiscoveredMission | None:
        """Build a login/signup mission from auth route analysis.

        Credentials are NEVER embedded in steps. The mission references a
        project credential by id; the runtime resolves the secret through
        CredentialStore at execution time.
        """
        path = auth_route["path"]
        is_signup = any(kw in path.lower() for kw in ["signup", "register", "create"])
        action = "Sign up" if is_signup else "Log in"

        steps = [
            {"type": "navigate", "url": auth_route["url"]},
            {"type": "wait", "value": "500"},
        ]
        if auth_route.get("has_form"):
            if not credential_id:
                # Without a configured credential we cannot honestly execute a
                # login journey. Emit the journey shell without credential steps
                # and mark it unverifiable via a NEEDS_INPUT-style objective.
                return DiscoveredMission(
                    id=f"mission-{uuid.uuid4().hex[:8]}",
                    name=f"{action} Flow (needs credentials)",
                    title=f"{action} to {title or 'application'}",
                    description=(
                        f"A {action.lower()} form was detected at {path}. Add a "
                        f"project credential so Kova can attempt this journey."
                    ),
                    objective=f"{action} to the application",
                    persona=persona,
                    category="auth",
                    journey=[
                        f"Navigate to {path}",
                        "Fill in credentials",
                        f"Complete {action.lower()} and verify access",
                    ],
                    steps=[],
                    successCondition=None,
                    confidence=0.4,
                    recommended=False,
                    route_analysis=auth_route,
                    estimated_time_seconds=20,
                )
            email_selector = "input[type='email'], input[name='email'], input[name='username']"
            password_selector = "input[type='password'], input[name='password']"
            steps.extend([
                {"type": "click", "target": email_selector},
                {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                {"type": "click", "target": password_selector},
                {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
                {"type": "click", "target": "button[type='submit'], button:has-text('Sign in'), button:has-text('Sign In'), button:has-text('Log in'), button:has-text('Log In'), button:has-text('Sign up'), button:has-text('Sign Up'), button:has-text('Create'), button:has-text('Continue'), input[type='submit']"},
                {"type": "wait", "value": "500"},
            ])

        # Strong verification: URL changed + password field absent + optional indicator
        if is_signup:
            success_condition = {
                "auth_verified": {
                    "auth_path": path,
                    "indicator": "check your email",
                }
            } if auth_route.get("has_form") else {
                "url_changed_from": path,
            }
        else:
            success_condition = {
                "auth_verified": {
                    "auth_path": path,
                }
            } if auth_route.get("has_form") else {
                "url_changed_from": path,
            }

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=f"{action} Flow",
            title=f"{action} to {title or 'application'}",
            description=f"Navigate to {path} and complete authentication",
            objective=f"Verify that {persona} can successfully {action.lower()}",
            persona=persona,
            category="auth",
            journey=[
                f"Navigate to {path}",
                "Fill in credentials" if auth_route.get("has_form") else "Interact with auth form",
                f"Complete {action.lower()} and verify access",
            ],
            steps=steps,
            successCondition=success_condition,
            confidence=0.88,
            recommended=False,
            route_analysis=auth_route,
            estimated_time_seconds=20,
        )

    async def _build_chained_auth_mission(
        self,
        signup_route: dict,
        login_route: dict,
        base_url: str,
        title: str,
        persona: str,
        credential_id: str | None = None,
    ) -> DiscoveredMission | None:
        """Build a chained signup -> login -> account mission.

        Uses the configured temp-mail service if available, or the project's
        credential_id if provided. If neither is available, emits a mission shell
        asking for one credential.
        """
        from app.engine.email import get_temp_email_provider

        temp_mail_provider = get_temp_email_provider()
        mailbox = None
        if temp_mail_provider:
            try:
                mailbox = await temp_mail_provider.create_mailbox()
            except Exception as e:
                logger.warning("Could not create temp mailbox for chained mission: %s", e)

        signup_path = signup_route.get("path", "/signup")
        login_path = login_route.get("path", "/login")
        signup_url = signup_route.get("url") or f"{base_url.rstrip('/')}{signup_path}"
        login_url = login_route.get("url") or f"{base_url.rstrip('/')}{login_path}"

        if not mailbox and not credential_id:
            # Need credential
            return DiscoveredMission(
                id=f"mission-{uuid.uuid4().hex[:8]}",
                name="Chained Auth Flow (needs credentials)",
                title=f"Sign up, log in, and verify account on {title or 'application'}",
                description=(
                    f"A signup route ({signup_path}) and login route ({login_path}) were detected. "
                    "Add a project credential or configure the temp-mail service to run this chained mission."
                ),
                objective=f"Verify that {persona} can sign up, log in, and view account page",
                persona=persona,
                category="auth",
                journey=[
                    f"Navigate to {signup_path}",
                    "Sign up with credentials",
                    f"Navigate to {login_path}",
                    "Log in with user credentials",
                    "Verify account page is displayed",
                ],
                steps=[],
                successCondition=None,
                confidence=0.5,
                recommended=False,
                route_analysis={"signup": signup_route, "login": login_route},
                estimated_time_seconds=30,
            )

        email_selector = "input[type='email'], input[name='email'], input[name='username']"
        password_selector = "input[type='password'], input[name='password']"
        submit_signup_selector = "button[type='submit'], input[type='submit'], button:has-text('Sign up'), button:has-text('Register'), button:has-text('Create')"
        submit_login_selector = "button[type='submit'], input[type='submit'], button:has-text('Log in'), button:has-text('Sign in')"

        steps = [
            {"type": "navigate", "url": signup_url},
            {"type": "wait", "value": "1000"},
            {"type": "click", "target": email_selector},
        ]

        if mailbox:
            email_val = mailbox.address
            pwd_val = f"KovaTest#{uuid.uuid4().hex[:6]}"
            steps.extend([
                {"type": "type", "target": email_selector, "value": email_val},
                {"type": "click", "target": password_selector},
                {"type": "type", "target": password_selector, "value": pwd_val},
            ])
        else:
            steps.extend([
                {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                {"type": "click", "target": password_selector},
                {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
            ])

        steps.extend([
            {"type": "click", "target": submit_signup_selector},
            {"type": "wait", "value": "500"},
            {"type": "navigate", "url": login_url},
            {"type": "wait", "value": "1000"},
            {"type": "click", "target": email_selector},
        ])

        if mailbox:
            steps.extend([
                {"type": "type", "target": email_selector, "value": email_val},
                {"type": "click", "target": password_selector},
                {"type": "type", "target": password_selector, "value": pwd_val},
            ])
        else:
            steps.extend([
                {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                {"type": "click", "target": password_selector},
                {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
            ])

        steps.extend([
            {"type": "click", "target": submit_login_selector},
            {"type": "wait", "value": "500"},
        ])

        success_condition = {
            "auth_verified": {
                "auth_path": login_path,
            }
        }

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name="Complete Registration and Login Journey",
            title=f"Sign up, log in, and view account on {title or 'application'}",
            description="Sign up as a new user, log in with credentials, and verify access to the account page.",
            objective=f"Verify that {persona} can sign up, log in, and view account page",
            persona=persona,
            category="auth",
            journey=[
                f"Navigate to {signup_path}",
                "Sign up with credentials",
                f"Navigate to {login_path}",
                "Log in with user credentials",
                "Verify account page is displayed",
            ],
            steps=steps,
            successCondition=success_condition,
            confidence=0.40,
            recommended=False,
            route_analysis={"signup": signup_route, "login": login_route},
            estimated_time_seconds=30,
        )

    def _build_standalone_form_mission(
        self,
        form_route: dict,
        base_url: str,
        title: str,
        persona: str,
    ) -> DiscoveredMission | None:
        """Build a standalone form mission (e.g. contact form).

        Executes: submit, then expect confirmation and no failed request.
        """
        path = form_route.get("path", "/contact")
        url = form_route.get("url") or f"{base_url.rstrip('/')}{path}"
        form_name = form_route.get("text") or form_route.get("title") or "Contact"
        if not form_name or form_name.strip() in {"/", ""}:
            form_name = "Contact"

        steps = [
            {"type": "navigate", "url": url},
            {"type": "wait", "value": "1000"},
            {"type": "click", "target": "input[name*='name'], input[id*='name'], input[placeholder*='name'], input[type='text']"},
            {"type": "type", "target": "input[name*='name'], input[id*='name'], input[placeholder*='name'], input[type='text']", "value": "Kova Tester"},
            {"type": "click", "target": "input[type='email'], input[name*='email'], input[id*='email'], input[placeholder*='email']"},
            {"type": "type", "target": "input[type='email'], input[name*='email'], input[id*='email'], input[placeholder*='email']", "value": "tester@example.com"},
            {"type": "click", "target": "textarea, input[name*='message'], input[id*='message'], input[placeholder*='message']"},
            {"type": "type", "target": "textarea, input[name*='message'], input[id*='message'], input[placeholder*='message']", "value": "This is an automated test message from Kova."},
            {"type": "click", "target": "button[type='submit'], input[type='submit'], button:has-text('Submit'), button:has-text('Send'), form button"},
            {"type": "wait", "value": "500"},
        ]

        # Expect confirmation and no failed request
        success_condition = {
            "text_visible": "Thank",
        }

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=f"Submit {form_name} Form",
            title=f"Submit {form_name.lower()} form on {title or 'application'}",
            description=f"Submit {form_name.lower()} form, then expect confirmation and no failed request.",
            objective=f"Submit {form_name.lower()} form, then expect confirmation and no failed request",
            persona=persona,
            category="form",
            journey=[
                f"Navigate to {path}",
                f"Fill in {form_name.lower()} details (name, email, message)",
                f"Submit the {form_name.lower()} form",
                "Expect confirmation and no failed request",
            ],
            steps=steps,
            successCondition=success_condition,
            confidence=0.8,
            recommended=False,
            route_analysis=form_route,
            estimated_time_seconds=15,
        )

    def _build_feature_mission(
        self,
        route: dict,
        base_url: str,
        title: str,
        persona: str,
        recommended: bool = False,
        all_capabilities: list[Any] | None = None,
    ) -> DiscoveredMission | None:
        """Build a navigation journey that proves the destination was reached.

        Verification = URL actually reflects the target route AND the page has
        meaningful content (not just a structural container existing).
        """
        if all_capabilities:
            cap = self._find_capability_for_route(route, all_capabilities)
            if not cap:
                return None
        path = route["path"]
        feature_name = route["text"] or path.split("/")[-1].replace("-", " ").title()
        is_settings_like = any(sk in path.lower() for sk in ["settings", "profile", "account", "preference"])
        if is_settings_like:
            recommended = False

        path_lower = path.lower()
        if any(k in path_lower for k in ["quiz", "exam", "test"]):
            mission_title = f"Practice and review {feature_name}"
            objective = f"Verify that {persona} can access {feature_name} and interact with quiz workflows"
        elif any(k in path_lower for k in ["study", "flashcard", "deck", "material", "course"]):
            mission_title = f"Explore {feature_name} study resources"
            objective = f"Verify that {persona} can view and study {feature_name}"
        elif any(k in path_lower for k in ["dashboard", "workspace", "portal", "console", "analytics"]):
            mission_title = f"Review {feature_name} overview and activity"
            objective = f"Confirm {feature_name} renders key metrics and interactive workflows"
        elif any(k in path_lower for k in ["create", "generate", "generator", "new"]):
            mission_title = f"Create new {feature_name}"
            objective = f"Verify that {persona} can access the {feature_name} creation workflow"
        else:
            mission_title = f"Explore {feature_name}"
            objective = f"Reach the {feature_name} page and confirm it renders interactive content"

        if route.get("is_button") and route.get("selector"):
            steps = [
                {"type": "navigate", "url": base_url},
                {"type": "wait", "value": "1000"},
                {"type": "click", "target": {"css": route["selector"]}},
                {"type": "wait", "value": "500"},
            ]
            journey_desc = [
                f"Open {title or 'the application'}",
                f"Click the '{feature_name}' action button",
                f"Verify the {feature_name} interactive interface is displayed",
            ]
            success_condition = {
                "element_count": {
                    "selector": "[role='dialog'], [role='region'], modal, .modal, form, input, textarea, h1, h2, h3, button",
                    "min": 1,
                },
            }
        else:
            steps = [
                {"type": "navigate", "url": route["url"]},
                {"type": "wait", "value": "500"},
            ]
            journey_desc = [
                f"Open {title or 'the application'}",
                f"Navigate to '{feature_name}' ({path})",
                f"Verify the {feature_name} page has loaded with content",
            ]
            success_condition = {
                "url_matches": re.escape(path.rstrip("/")).replace("\\/", "/") or path,
                "element_count": {"selector": "a[href], button", "min": 1},
            }

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=mission_title,
            title=mission_title,
            description=(
                f"Activate '{feature_name}' and verify the destination "
                f"interface loads with interactive content."
            ),
            objective=objective,
            persona=persona,
            category="feature",
            journey=journey_desc,
            steps=steps,
            successCondition=success_condition,
            confidence=0.72,
            recommended=recommended,
            route_analysis=route,
            estimated_time_seconds=12,
        )

    def _build_content_mission(
        self, route: dict, base_url: str, title: str, persona: str, recommended: bool = False
    ) -> DiscoveredMission | None:
        """Build a content-browsing journey that proves content was exposed.

        Verifies the route serves real link/interactive content rather than an
        empty shell. If no content signal exists the journey says so honestly.
        """
        path = route["path"]
        content_name = route["text"] or path.split("/")[-1].replace("-", " ").title()
        path_lower = path.lower()
        if any(k in path_lower for k in ["explore", "discover"]):
            content_title = f"Explore and discover {content_name}"
        elif any(k in path_lower for k in ["library", "catalog", "collection"]):
            content_title = f"Browse {content_name} library"
        else:
            content_title = f"Browse {content_name}"

        steps = [
            {"type": "navigate", "url": route["url"]},
            {"type": "wait", "value": "500"},
        ]

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=content_title,
            title=content_title,
            description=(
                f"Open {content_name} and verify that it exposes real content "
                f"(links or resources) rather than an empty page."
            ),
            objective=f"Confirm {content_name} serves browsable content",
            persona=persona,
            category="content",
            journey=[
                f"Open {title or 'the application'}",
                f"Navigate to '{content_name}' ({path})",
                f"Verify {content_name} lists real content",
            ],
            steps=steps,
            successCondition={
                "url_matches": re.escape(path.rstrip("/")).replace("\\/", "/") or path,
                "element_count": {"selector": "a[href]", "min": 1},
            },
            confidence=0.70,
            recommended=recommended,
            route_analysis=route,
            estimated_time_seconds=12,
        )

    def _build_element_mission(
        self, element: dict, base_url: str, title: str, persona: str, recommended: bool = False
    ) -> DiscoveredMission | None:
        """Build a meaningful multi-step journey from a DOM element.

        Classifies user intent and generates appropriate journey with success criteria.
        A JOURNEY IS NOT A ROUTE. A JOURNEY REPRESENTS A USER INTENT
        THAT CAN BE EXECUTED AND VERIFIED.
        """
        el_name = element.get("name", "").strip()
        el_type = element.get("type", "button")
        selector = element.get("selector")

        if not selector or not selector.startswith("#"):
            clean_name = el_name.replace("'", "\\'")
            if el_type == "link":
                selector = f"a:has-text('{clean_name}')"
            else:
                selector = f"button:has-text('{clean_name}'), [role='button']:has-text('{clean_name}')"

        # Classify user intent from element name and context
        intent = self._classify_intent(el_name)

        # Generate journey based on intent (auth journeys reference credentials)
        journey_data = self._build_journey_for_intent(
            intent, el_name, selector, base_url, title, persona,
            credential_id=self.credential_id,
        )

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=journey_data["name"],
            title=journey_data["name"],
            description=journey_data["description"],
            objective=journey_data["objective"],
            persona=persona,
            category=journey_data["category"],
            journey=journey_data["journey"],
            steps=journey_data["steps"],
            successCondition=journey_data["success_condition"],
            confidence=journey_data["confidence"],
            recommended=recommended,
            estimated_time_seconds=journey_data["estimated_time"],
        )

    def _classify_intent(self, element_name: str) -> str:
        """Classify user intent from element/button text.

        Maps UI text to meaningful user goals, not just "click this button".
        """
        lower = element_name.lower().strip()

        # Account / Auth intents
        if any(kw in lower for kw in ["get started", "sign up", "register", "create account", "join"]):
            return "create_account"
        if any(kw in lower for kw in ["log in", "login", "sign in", "continue with"]):
            return "login"
        if any(kw in lower for kw in ["logout", "sign out", "log out"]):
            return "logout"

        # Search / Discovery intents
        if any(kw in lower for kw in ["search", "find", "lookup", "discover"]):
            return "search"
        if any(kw in lower for kw in ["browse", "explore", "view all", "see all", "view library", "catalog"]):
            return "browse"

        # Content / Resource intents
        if any(kw in lower for kw in ["preview", "view", "open", "read", "watch", "play"]):
            return "view_content"
        if any(kw in lower for kw in ["download", "export", "save", "bookmark"]):
            return "download"
        if any(kw in lower for kw in ["upload", "import", "create new", "add"]):
            return "create_content"

        # Transactional intents
        if any(kw in lower for kw in ["buy", "purchase", "subscribe", "upgrade", "checkout", "pay"]):
            return "purchase"
        if any(kw in lower for kw in ["submit", "send", "confirm", "apply"]):
            return "submit"
        if any(kw in lower for kw in ["edit", "modify", "update", "change", "settings", "configure"]):
            return "configure"

        # Navigation intents
        if any(kw in lower for kw in ["dashboard", "home", "main", "overview"]):
            return "navigate_dashboard"
        if any(kw in lower for kw in ["profile", "account", "my page"]):
            return "view_profile"
        if any(kw in lower for kw in ["help", "support", "docs", "documentation", "faq"]):
            return "get_help"
        if any(kw in lower for kw in ["contact", "feedback", "report"]):
            return "contact"

        # Default: treat as a feature to explore
        return "explore_feature"

    def _build_journey_for_intent(
        self, intent: str, el_name: str, selector: str, base_url: str, title: str, persona: str,
        credential_id: str | None = None,
    ) -> dict:
        """Generate a multi-step journey with outcome-verifying success criteria.

        Every generated condition must prove the user outcome, not merely that
        an action executed or that a structural container exists. When the
        observed DOM does not support honest verification, the journey says so
        (confidence lowered / success condition left to runtime UNVERIFIED).
        """

        app_name = title or "the application"

        if intent == "create_account":
            if not credential_id:
                return {
                    "name": "Create an account (needs credentials)",
                    "description": (
                        "A registration entry point was detected. Add a project "
                        "credential so Kova can attempt account creation."
                    ),
                    "objective": "Create an account and reach the authenticated experience",
                    "category": "auth",
                    "journey": [
                        f"Open {app_name}",
                        f"Use the registration entry point '{el_name}'",
                        "Complete registration (requires configured credentials)",
                    ],
                    "steps": [],
                    "success_condition": None,
                    "confidence": 0.4,
                    "estimated_time": 25,
                }
            email_selector = "input[type='email'], input[name='email'], input[name='username']"
            password_selector = "input[type='password'], input[name='password']"
            return {
                "name": "Create an account",
                "description": f"Verify that {persona.lower()} can register and reach the authenticated experience.",
                "objective": f"Verify that {persona} can create an account and access the platform",
                "category": "auth",
                "journey": [
                    f"Open {app_name}",
                    f"Use the registration entry point '{el_name}'",
                    "Complete the registration form with the configured test credential",
                    "Submit registration",
                    "Verify the authenticated experience is reached",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                    {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                    {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
                    {"type": "click", "target": "button[type='submit'], button:has-text('Sign up'), button:has-text('Sign Up'), button:has-text('Create'), button:has-text('Register'), button:has-text('Continue'), input[type='submit']"},
                    {"type": "wait", "value": "500"},
                ],
                "success_condition": {
                    "auth_verified": {"auth_path": "/register"},
                },
                "confidence": 0.7,
                "estimated_time": 25,
            }

        if intent == "search":
            # Search journey: enter a deterministic query, submit, then verify a
            # results state — result links appear OR the URL reflects the query.
            # Not "the search input exists".
            search_input = "input[type='search'], input[name='q'], input[placeholder*='earch' i], input[placeholder*='ind' i], input[aria-label*='search' i]"
            return {
                "name": "Search for resources",
                "description": (
                    f"Use the site search to look for resources: open the search "
                    f"interface, run a query, and verify a results state appears."
                ),
                "objective": f"Verify that {persona} can search and the application returns a results state",
                "category": "feature",
                "journey": [
                    f"Open {app_name}",
                    f"Open the search interface via '{el_name}'",
                    "Enter a search query",
                    "Submit the search",
                    "Verify a results state (result links or query-reflected URL)",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                    {"type": "type", "target": search_input, "value": "course"},
                    {"type": "click", "target": "button[type='submit'], button:has-text('Search')"},
                    {"type": "wait", "value": "500"},
                ],
                # Outcome proof: at least one result link rendered, OR the URL
                # began reflecting the query. Weak/absent result states are
                # reported honestly by the runner as verification failure.
                "success_condition": {
                    "element_count": {
                        "selector": "a[href], [role='link'], article, li",
                        "min": 1,
                    },
                },
                "confidence": 0.7,
                "estimated_time": 20,
            }

        if intent == "browse":
            return {
                "name": f"Browse {el_name}",
                "description": (
                    f"Open {el_name} and verify it exposes real browsable content "
                    f"(links or resource entries), not an empty shell."
                ),
                "objective": f"Verify that {persona} can access {el_name} and see real content",
                "category": "content",
                "journey": [
                    f"Open {app_name}",
                    f"Navigate to '{el_name}'",
                    "Verify real content entries are available",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                ],
                "success_condition": {
                    "url_changed_to": {"from": base_url},
                    "element_count": {"selector": "a[href]", "min": 1},
                },
                "confidence": 0.65,
                "estimated_time": 15,
            }

        if intent == "view_content":
            return {
                "name": f"Open '{el_name}' content",
                "description": (
                    f"Open {el_name} and verify a content view actually renders "
                    f"with a distinct heading."
                ),
                "objective": f"Verify that {persona} can open and view the content",
                "category": "content",
                "journey": [
                    f"Open {app_name}",
                    f"Open '{el_name}'",
                    "Verify the content view renders",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                ],
                # State change proof: page must actually present a heading.
                # Structural containers are deliberately NOT accepted as proof.
                "success_condition": {
                    "element_count": {"selector": "h1, h2, [role='heading']", "min": 1},
                },
                "confidence": 0.6,
                "estimated_time": 15,
            }

        if intent == "login":
            if not credential_id:
                return {
                    "name": "Log in to account (needs credentials)",
                    "description": (
                        "A login entry point was detected. Add a project credential "
                        "so Kova can attempt this journey."
                    ),
                    "objective": "Log in and reach the authenticated experience",
                    "category": "auth",
                    "journey": [
                        f"Open {app_name}",
                        "Navigate to login",
                        "Enter credentials (requires configured credentials)",
                        "Verify authenticated state",
                    ],
                    "steps": [],
                    "success_condition": None,
                    "confidence": 0.4,
                    "estimated_time": 20,
                }
            email_selector = "input[type='email'], input[name='email'], input[name='username']"
            password_selector = "input[type='password'], input[name='password']"
            return {
                "name": "Log in to account",
                "description": f"Verify that {persona.lower()} can authenticate and reach the post-login state.",
                "objective": f"Verify that {persona} can log in successfully",
                "category": "auth",
                "journey": [
                    f"Open {app_name}",
                    f"Use the login entry point '{el_name}'",
                    "Enter the configured test credentials",
                    "Submit the login form",
                    "Verify the authenticated state (URL leaves the login path, password field gone)",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                    {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                    {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
                    {"type": "click", "target": "button[type='submit'], button:has-text('Log in'), button:has-text('Log In'), button:has-text('Sign in'), button:has-text('Sign In'), button:has-text('Continue'), input[type='submit']"},
                    {"type": "wait", "value": "500"},
                ],
                "success_condition": {
                    "auth_verified": {"auth_path": "/login"},
                },
                "confidence": 0.7,
                "estimated_time": 20,
            }

        if intent == "navigate_dashboard":
            return {
                "name": f"Open {el_name}",
                "description": (
                    f"Navigate to {el_name} and verify the destination page loads "
                    f"with real interactive content."
                ),
                "objective": f"Verify that {persona} can reach {el_name}",
                "category": "feature",
                "journey": [
                    f"Open {app_name}",
                    f"Navigate to '{el_name}'",
                    "Verify the destination page has loaded with content",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                ],
                "success_condition": {
                    "url_changed_to": {"from": base_url},
                    "element_count": {"selector": "a[href], button", "min": 1},
                },
                "confidence": 0.65,
                "estimated_time": 12,
            }

        if intent == "purchase":
            return {
                "name": f"Open purchase flow",
                "description": (
                    f"Open the '{el_name}' flow and verify a purchasing-related page "
                    f"renders. Kova will NOT complete payments without explicit "
                    f"human confirmation."
                ),
                "objective": f"Verify that {persona} can reach the purchase flow",
                "category": "feature",
                "journey": [
                    f"Open {app_name}",
                    f"Open '{el_name}'",
                    "Verify the purchase-related page renders",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                ],
                "success_condition": {
                    "url_changed_to": {"from": base_url},
                },
                "confidence": 0.5,
                "estimated_time": 15,
            }

        if intent == "get_help":
            return {
                "name": f"Open {el_name} resources",
                "description": (
                    f"Open {el_name} and verify documentation/help content renders "
                    f"with a heading and links."
                ),
                "objective": f"Verify that {persona} can access {el_name} resources",
                "category": "content",
                "journey": [
                    f"Open {app_name}",
                    f"Navigate to '{el_name}'",
                    "Verify documentation content renders",
                ],
                "steps": [
                    {"type": "navigate", "url": base_url},
                    {"type": "click", "target": selector},
                    {"type": "wait", "value": "500"},
                ],
                "success_condition": {
                    "url_changed_to": {"from": base_url},
                    "element_count": {"selector": "a[href]", "min": 1},
                },
                "confidence": 0.6,
                "estimated_time": 12,
            }

        # Default: bounded navigation check with honest description.
        return {
            "name": f"Open {el_name}",
            "description": (
                f"Use the '{el_name}' control and verify the application visibly "
                f"responds (page state changes)."
            ),
            "objective": f"Verify that {persona} can use '{el_name}' and the app responds",
            "category": "feature",
            "journey": [
                f"Open {app_name}",
                f"Use '{el_name}'",
                "Verify the application state changes in response",
            ],
            "steps": [
                {"type": "navigate", "url": base_url},
                {"type": "click", "target": selector},
                {"type": "wait", "value": "500"},
            ],
            "success_condition": {
                "url_changed_to": {"from": base_url},
            },
            "confidence": 0.55,
            "estimated_time": 10,
        }

    def _generate_recommendation(self, missions: list[DiscoveredMission]) -> str:
        if getattr(self, "_ai_recommendation_reason", None):
            return self._ai_recommendation_reason
        if self.goal:
            return f"I mapped this workflow specifically around your requested goal: '{self.goal}'."

        recommended_missions = [m for m in missions if m.recommended]
        if recommended_missions:
            rec = recommended_missions[0]
            feature_name = rec.title or rec.name
            return (
                f"I discovered {len(missions)} journeys and recommend '{feature_name}' "
                f"to validate core application features and user workflows."
            )
        if len(missions) >= 2:
            return f"I found {len(missions)} user journeys. The recommended journeys cover the primary user workflow."
        return "I found 1 primary user journey to get started."
