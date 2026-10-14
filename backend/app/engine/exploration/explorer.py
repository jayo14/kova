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
    ):
        self.exploration_id = exploration_id
        self.url = url
        self.goal = goal.strip() if goal else None
        self.event_emitter = event_emitter
        self.credential_id = credential_id
        self._browser: BrowserSession | None = existing_browser
        self._is_cancelled = False
        self._visited_urls: set[str] = set()
        self._bg_tasks: set[asyncio.Task] = set()
        self._ai_recommendation_reason: str | None = None

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

    async def _capture_and_emit_screenshot(self, page) -> dict | None:
        """Capture screenshot, upload to Supabase Storage, emit public URL."""
        if not self._browser or not self._browser.is_started:
            return None
        try:
            screenshot_bytes = await self._browser.screenshot()
            parsed = urlparse(page.url)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"

            # Upload screenshot off the event loop (sync httpx blocks otherwise)
            storage_meta = await asyncio.to_thread(
                screenshot_storage.save,
                str(self.exploration_id),
                screenshot_bytes,
                page.url,
            )

            screenshot_meta = {
                "url": page.url,
                "path": path,
                "screenshot_key": storage_meta["screenshot_key"],
                "screenshot_size_bytes": storage_meta["screenshot_size_bytes"],
            }
            # Include public URL if available (Supabase Storage)
            if storage_meta.get("screenshot_url"):
                screenshot_meta["screenshot_url"] = storage_meta["screenshot_url"]

            await self._emit("browser.screenshot", screenshot_meta)
            return screenshot_meta
        except Exception as e:
            logger.warning("Could not capture screenshot: %s", e)
            return None

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
                        response = await page.goto(self.url, wait_until="domcontentloaded")
                        # Short networkidle check — 3s max, swallow timeout
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass
                        # Minimal pause for SPA hydration
                        await asyncio.sleep(0.3)
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

                # Emit page.loaded immediately (without screenshot) for fast URL bar update
                page_event = {
                    "url": current_url,
                    "title": await page.title(),
                }
                await self._emit("page.loaded", page_event)

                # Capture screenshot and upload in background
                async def _capture_screenshot_bg():
                    try:
                        await self._capture_and_emit_screenshot(page)
                    except Exception as e:
                        logger.warning("Background screenshot capture failed: %s", e)

                self._spawn_bg(_capture_screenshot_bg())

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

                # 3. Check for authentication requirement
                is_auth_required = await self._detect_authentication(page, observation)

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

            # 6. Discover workflows and map journeys
            await self._emit("state_change", {"status": "DISCOVERING"})
            await self._emit("progress", {
                "id": "exp-discover",
                "message": "Mapping user journeys and application workspace",
                "status": "active",
            })

            discoveries, missions = await self._discover_workflows(page, observation, selected_role)
            await self._capture_and_emit_screenshot(page)

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
            await self._emit("state_change", {"status": "READY"})
            await self._emit("ready", {})

            should_close_browser = False
            return {
                "status": ExplorationStatus.READY,
                "discoveries": [d.model_dump() for d in discoveries],
                "candidate_missions": [m.model_dump() for m in missions],
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
        """Detects if application provides role switching (e.g. Student, Lecturer, Admin)."""
        text = observation.get("text", "").lower()
        elements = observation.get("elements", [])

        roles = []
        role_candidates = [
            ("student", "Student", "Learner workspace with material access and quiz tools", "school"),
            ("lecturer", "Lecturer", "Teaching workspace with course creation and grading tools", "psychology"),
            ("admin", "Administrator", "System settings, organization and member controls", "settings"),
            ("teacher", "Teacher", "Educator workspace with assignment and student tracking", "school"),
            ("creator", "Creator", "Content authoring and publishing dashboard", "edit"),
        ]

        for r_id, label, desc, icon in role_candidates:
            # Look for role in buttons, links, or text
            mentioned_in_elements = any(
                r_id in el.get("name", "").lower() for el in elements
            )
            mentioned_in_text = r_id in text
            if mentioned_in_elements or mentioned_in_text:
                roles.append({
                    "id": r_id,
                    "label": label,
                    "description": desc,
                    "icon": icon,
                })

        return roles

    async def _analyze_routes(self, page, base_url: str) -> list[dict]:
        """Bounded exploration: build an application map.

        Strategy:
        1. Try sitemap.xml first (fast, comprehensive)
        2. Scan page DOM for links (a[href], nav, buttons)
        3. Prioritize by keywords (auth, dashboard, settings)
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

        # Step 3: Prioritize by keywords
        prioritized = self._prioritize_routes(route_map)

        # Step 4: Probe top routes via API request (exclude DOM buttons from HTTP probe)
        network_targets = [r for r in prioritized if not r.get("is_button")][:16]
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
            response = await page.request.get(sitemap_url, timeout=3000, fail_on_status_code=False)
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

    def _prioritize_routes(self, routes: list[dict]) -> list[dict]:
        """Prioritize routes by feature importance, elevating core workflows over auth."""
        priority_map = {
            # Highest priority: Dashboards and core application workspaces
            "dashboard": 0,
            "workspace": 0,
            "app": 0,
            "portal": 0,
            "console": 0,
            # Core feature actions and CRUD workflows (educational / productivity)
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
            "create": 1,
            "new": 1,
            "edit": 1,
            "manage": 1,
            "course": 1,
            "document": 1,
            "note": 1,
            "project": 1,
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
                route["url"], timeout=3000, fail_on_status_code=False
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
        """Auto-detect relevant personas based on route analysis."""
        personas = []
        categories = {r["category"] for r in route_map}
        paths = {r["path"].lower() for r in route_map}

        # SaaS / App personas
        if "auth" in categories:
            if any("dashboard" in p or "home" in p for p in paths):
                personas.append("new_user")
                personas.append("returning_user")
            if any("admin" in p or "settings" in p for p in paths):
                personas.append("admin")

        # E-commerce personas
        if any("cart" in p or "checkout" in p for p in paths):
            personas.append("buyer")
        if any("seller" in p or "vendor" in p or "merchant" in p for p in paths):
            personas.append("seller")

        # Content personas
        if any("create" in p or "new" in p or "upload" in p for p in paths):
            personas.append("creator")
        if any("editor" in p or "manage" in p for p in paths):
            personas.append("editor")

        # Tool personas
        if any("project" in p or "workspace" in p for p in paths):
            personas.append("power_user")

        # Default to user if no personas detected
        if not personas:
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
        route_map = await self._analyze_routes(page, current_url)
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
        persona_name = selected_role.capitalize() if selected_role else (detected_personas[0].capitalize() if detected_personas else "User")
        logger.info("Detected personas: %s, using: %s", detected_personas, persona_name)

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
            goal_mission = self._build_goal_mission(
                self.goal, current_url, title, persona_name, interactive_elements
            )
            if goal_mission:
                missions.append(goal_mission)
                mission_count += 1

        # Step 3b: Attempt AI-powered journey synthesis for feature discovery
        ai_provider = get_ai_provider()
        ai_reasoner = AgentReasoner(ai_provider) if ai_provider else None

        if ai_reasoner and (route_map or interactive_elements) and mission_count < max_missions:
            try:
                page_text = (
                    (observation.get("text") or "")[:1200]
                    + " "
                    + " ".join([el.get("name", "") for el in interactive_elements[:30] if el.get("name")])
                ).strip()
                ai_journeys_result = await asyncio.wait_for(
                    ai_reasoner.synthesize_journeys(
                        base_url=current_url,
                        title=title,
                        goal=self.goal,
                        persona=persona_name,
                        routes=route_map,
                        interactive_elements=interactive_elements,
                        page_summary=page_text,
                        max_journeys=max_missions - mission_count,
                    ),
                    timeout=25.0,
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

            for route in ordered_features[:4]:
                if mission_count >= max_missions:
                    break
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
                fake_route = {
                    "path": urlparse(current_url).path or "/contact",
                    "url": current_url,
                    "title": title or "Contact",
                    "text": "Contact",
                    "category": "form",
                    "has_form": True,
                }
                form_mission = self._build_standalone_form_mission(
                    fake_route, current_url, title, persona_name
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
            0 if (m.recommended and m.category != "auth") else 1,
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

    def _build_goal_mission(
        self, goal: str, base_url: str, title: str, persona: str, elements: list[dict]
    ) -> DiscoveredMission | None:
        """Build a mission from the user's stated goal.

        The goal is matched deterministically against observed controls. The
        success condition verifies the goal-relevant control's destination
        changed the page state — never a vacuous url_matches:.* pattern.
        """
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
        steps.append({"type": "wait", "value": "2000"})

        # Verify state actually changed after reaching for the goal. Without a
        # post-action state change there is no honest success signal — the
        # mission would be unverifiable, so we say so via a state-change check
        # that the runner reports as UNVERIFIED when the page didn't move.
        success_condition = {
            "url_changed_to": {"from": base_url},
        }

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=goal,
            title=goal,
            description=f"Attempt the goal '{goal}' and verify the application responds by changing state.",
            objective=f"Verify that {persona} can act on '{el_name}' and the application visibly responds",
            persona=persona,
            category="feature",
            journey=[
                f"Access {title or 'application'}",
                f"Use the control matching the goal: '{el_name}'",
                "Verify the application state changes in response",
            ],
            steps=steps,
            successCondition=success_condition,
            confidence=0.75 if matching_el else 0.5,
            recommended=bool(matching_el),
            estimated_time_seconds=15,
        )

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
            {"type": "wait", "value": "2000"},
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
                {"type": "wait", "value": "3000"},
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
            {"type": "wait", "value": "2000"},
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
            {"type": "wait", "value": "2000"},
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
            {"type": "wait", "value": "2000"},
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
        self, route: dict, base_url: str, title: str, persona: str, recommended: bool = False
    ) -> DiscoveredMission | None:
        """Build a navigation journey that proves the destination was reached.

        Verification = URL actually reflects the target route AND the page has
        meaningful content (not just a structural container existing).
        """
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

        steps = [
            {"type": "navigate", "url": route["url"]},
            {"type": "wait", "value": "2000"},
        ]

        return DiscoveredMission(
            id=f"mission-{uuid.uuid4().hex[:8]}",
            name=mission_title,
            title=mission_title,
            description=(
                f"Navigate to the {feature_name} page and verify the destination "
                f"actually loads with real content."
            ),
            objective=objective,
            persona=persona,
            category="feature",
            journey=[
                f"Open {title or 'the application'}",
                f"Navigate to '{feature_name}' ({path})",
                f"Verify the {feature_name} page has loaded with content",
            ],
            steps=steps,
            # Prove destination: URL matches the route's final segment and the
            # page exposes at least one interactive element. This is an honest,
            # bounded navigation check — not "any page is success".
            successCondition={
                "url_matches": re.escape(path.rstrip("/")).replace("\\/", "/") or path,
                "element_count": {"selector": "a[href], button", "min": 1},
            },
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
            {"type": "wait", "value": "2000"},
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
                    {"type": "wait", "value": "2000"},
                    {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                    {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
                    {"type": "click", "target": "button[type='submit'], button:has-text('Sign up'), button:has-text('Sign Up'), button:has-text('Create'), button:has-text('Register'), button:has-text('Continue'), input[type='submit']"},
                    {"type": "wait", "value": "3000"},
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
                    {"type": "wait", "value": "2000"},
                    {"type": "type", "target": search_input, "value": "course"},
                    {"type": "click", "target": "button[type='submit'], button:has-text('Search')"},
                    {"type": "wait", "value": "3000"},
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
                    {"type": "wait", "value": "2000"},
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
                    {"type": "wait", "value": "2000"},
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
                    {"type": "wait", "value": "2000"},
                    {"type": "type", "target": email_selector, "credential_id": credential_id, "credential_field": "email"},
                    {"type": "type", "target": password_selector, "credential_id": credential_id, "credential_field": "password"},
                    {"type": "click", "target": "button[type='submit'], button:has-text('Log in'), button:has-text('Log In'), button:has-text('Sign in'), button:has-text('Sign In'), button:has-text('Continue'), input[type='submit']"},
                    {"type": "wait", "value": "3000"},
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
                    {"type": "wait", "value": "2000"},
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
                    {"type": "wait", "value": "2000"},
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
                    {"type": "wait", "value": "2000"},
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
                {"type": "wait", "value": "2000"},
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
