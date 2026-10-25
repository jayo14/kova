"""Authentication barrier detection and automated authentication helpers.

Provides shared routines for detecting when a target URL is behind an
auth wall (e.g. /settings redirecting to /signin), and intelligently
logging in using available test account credentials.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import inspect
import logging
import re
from urllib.parse import urlparse
from typing import Any

from app.engine.ai.schemas import AuthPageClassification

logger = logging.getLogger(__name__)

AUTH_URL_PATTERNS = [
    r"/sign-?in\b",
    r"/log-?in\b",
    r"/auth\b",
    r"/session\b",
    r"/register\b",
    r"/sign-?up\b",
    r"/accounts/login\b",
    r"/accounts/signin\b",
    r"/user/login\b",
    r"/app/login\b",
]

OAUTH_KEYWORDS = ["google", "github", "apple", "microsoft", "facebook", "twitter", "sso", "saml", "okta"]
COMMON_SUBMIT_TERMS = [
    "sign in", "signin", "log in", "login",
    "sign up", "signup", "create account", "register",
    "continue", "submit", "next",
]


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    s1 = s1.strip().lower()
    s2 = s2.strip().lower()
    if s1 == s2:
        return 0
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


class AuthFailureCategory(str, Enum):
    CLIENT_VALIDATION = "client_validation"
    REQUIRED_CONSENT = "required_consent"
    CUSTOM_FIELDS_REQUIRED = "custom_fields_required"
    SERVER_REJECTION = "server_rejection"
    EMAIL_VERIFICATION_REQUIRED = "email_verification_required"
    RATE_LIMITED = "rate_limited"
    CAPTCHA_REQUIRED = "captcha_required"
    HUMAN_INTERVENTION_REQUIRED = "human_intervention_required"
    ACCOUNT_ALREADY_CREATED = "account_already_created"
    UNKNOWN = "unknown"


@dataclass
class AuthFailureDiagnosis:
    category: str
    detail: str
    missing_fields: list[str] = field(default_factory=list)
    invalid_fields: list[dict[str, str]] = field(default_factory=list)
    server_error: str | None = None
    unfilled_required_fields: list[dict[str, str]] = field(default_factory=list)
    captcha_detected: bool = False
    email_verification_detected: bool = False
    consent_required: list[str] = field(default_factory=list)
    can_retry_autonomously: bool = False
    recommended_recovery_action: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthSignalBundle:
    url_path_is_auth: bool
    visible_password_input_count: int
    visible_email_input_count: int
    visible_otp_input_count: int
    has_remember_me_checkbox: bool
    has_forgot_password_link: bool
    oauth_button_texts: list[str] = field(default_factory=list)
    magic_link_form_markers: list[str] = field(default_factory=list)
    submit_button_texts: list[str] = field(default_factory=list)
    url: str = ""


def is_auth_url(url: str | None) -> bool:
    """Return True if the URL path matches common authentication endpoints."""
    if not url:
        return False
    path = urlparse(url).path.lower()
    return any(re.search(pat, path) for pat in AUTH_URL_PATTERNS)


async def observe_auth_signals(page: Any, url: str | None = None) -> AuthSignalBundle:
    """Observe multi-signal auth indicators from URL and DOM deterministically."""
    current_url = url or getattr(page, "url", "") or ""
    url_is_auth = is_auth_url(current_url)

    pwd_count = 0
    email_count = 0
    otp_count = 0
    has_remember = False
    has_forgot = False
    oauth_button_texts: list[str] = []
    magic_link_form_markers: list[str] = []
    submit_button_texts: list[str] = []

    if page is not None and hasattr(page, "locator"):
        # Password inputs
        try:
            pwd_loc = page.locator('input[type="password"]')
            count = pwd_loc.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                el = pwd_loc.nth(i)
                vis = el.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if vis:
                    pwd_count += 1
        except Exception:
            pass

        # Email / username inputs
        try:
            email_loc = page.locator(
                'input[type="email"], input[name*="email" i], input[id*="email" i], '
                'input[placeholder*="email" i], input[name*="username" i], input[id*="username" i]'
            )
            count = email_loc.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                el = email_loc.nth(i)
                vis = el.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if vis:
                    email_count += 1
        except Exception:
            pass

        # OTP inputs
        try:
            otp_loc = page.locator(
                'input[name*="otp" i], input[name*="code" i], input[id*="otp" i], '
                'input[autocomplete="one-time-code"], input[inputmode="numeric"][maxlength="6"]'
            )
            count = otp_loc.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                el = otp_loc.nth(i)
                vis = el.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if vis:
                    otp_count += 1
        except Exception:
            pass

        # Remember me checkbox
        try:
            rem_loc = page.locator('input[type="checkbox"][name*="remember" i], input[type="checkbox"][id*="remember" i]')
            count = rem_loc.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                el = rem_loc.nth(i)
                vis = el.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if vis:
                    has_remember = True
                    break
        except Exception:
            pass

        # Forgot password links
        try:
            forgot_loc = page.locator('a[href*="forgot" i], a[href*="reset" i], a:has-text("Forgot"), button:has-text("Forgot")')
            count = forgot_loc.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                el = forgot_loc.nth(i)
                vis = el.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if vis:
                    has_forgot = True
                    break
        except Exception:
            pass

        # Buttons and submit markers
        try:
            btn_loc = page.locator('button, [role="button"], input[type="submit"]')
            count = btn_loc.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                el = btn_loc.nth(i)
                vis = el.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if not vis:
                    continue
                txt_call = el.inner_text(timeout=300)
                if inspect.isawaitable(txt_call):
                    txt_raw = await txt_call
                else:
                    txt_raw = txt_call or ""
                txt = (txt_raw or "").strip()
                lower = txt.lower()

                if any(oa in lower for oa in OAUTH_KEYWORDS):
                    oauth_button_texts.append(txt)
                else:
                    if txt:
                        submit_button_texts.append(txt)
                    if any(ml in lower for ml in ["magic", "email me a link", "send link", "send login link"]):
                        magic_link_form_markers.append(txt)
        except Exception:
            pass

    return AuthSignalBundle(
        url_path_is_auth=url_is_auth,
        visible_password_input_count=pwd_count,
        visible_email_input_count=email_count,
        visible_otp_input_count=otp_count,
        has_remember_me_checkbox=has_remember,
        has_forgot_password_link=has_forgot,
        oauth_button_texts=oauth_button_texts,
        magic_link_form_markers=magic_link_form_markers,
        submit_button_texts=submit_button_texts,
        url=current_url,
    )


def classify_auth_page(bundle: AuthSignalBundle) -> AuthPageClassification:
    """Classify authentication page type deterministically from multi-signal bundle."""
    # 1. OTP Verification
    if bundle.visible_otp_input_count > 0 and bundle.visible_password_input_count == 0:
        return AuthPageClassification(
            kind="otp_verification",
            confidence=1.0,
            reasoning="OTP or verification code input visible without standard password form.",
        )

    # 2. Magic Link
    if bundle.visible_password_input_count == 0 and bundle.visible_email_input_count > 0:
        has_magic_text = any(
            any(ml in t.lower() for ml in ["magic", "email me a link", "send link", "email link"])
            for t in bundle.submit_button_texts
        ) or bool(bundle.magic_link_form_markers)
        if has_magic_text:
            return AuthPageClassification(
                kind="magic_link",
                confidence=1.0,
                reasoning="Email input with magic link submission marker present.",
            )

    # 3. OAuth redirect / SSO-only gate
    if bundle.oauth_button_texts and bundle.visible_password_input_count == 0 and bundle.visible_email_input_count == 0:
        return AuthPageClassification(
            kind="oauth_redirect",
            confidence=1.0,
            reasoning="Third-party OAuth/SSO buttons present with no native credentials form.",
        )

    # 4. Signup form
    if bundle.visible_password_input_count > 0:
        signup_btn = any(
            any(sw in t.lower() for sw in ["sign up", "signup", "register", "create account", "join"])
            for t in bundle.submit_button_texts
        )
        url_lower = bundle.url.lower()
        signup_url = any(sw in url_lower for sw in ["signup", "sign-up", "register"])
        if signup_btn or signup_url:
            return AuthPageClassification(
                kind="signup",
                confidence=1.0,
                reasoning="Password and credential inputs accompanied by registration signals.",
            )

        # 5. Login form (DOM signal wins over URL)
        return AuthPageClassification(
            kind="login",
            confidence=1.0,
            reasoning="Visible password input and credential form elements detected.",
        )

    # 6. Ambiguous state (URL says auth, but page has 0 inputs — still loading or blank)
    if bundle.url_path_is_auth and bundle.visible_password_input_count == 0 and bundle.visible_email_input_count == 0:
        return AuthPageClassification(
            kind="ambiguous",
            confidence=0.4,
            reasoning="URL path matches auth endpoint but no form inputs are visible in DOM (page may still be loading).",
        )

    # 7. Not an auth page
    return AuthPageClassification(
        kind="not_auth",
        confidence=1.0,
        reasoning="No authentication inputs, credentials, or auth endpoint patterns detected.",
    )


async def is_auth_page(page: Any, url: str | None = None) -> bool:
    """Return True if the page URL or DOM indicates an authentication barrier."""
    current_url = url or getattr(page, "url", "")
    bundle = await observe_auth_signals(page, current_url)
    classification = classify_auth_page(bundle)
    if classification.kind in {"login", "signup", "magic_link", "otp_verification", "oauth_redirect"}:
        return True
    if classification.kind == "ambiguous":
        return bundle.url_path_is_auth or bundle.visible_password_input_count > 0
    return False


def is_auth_barrier(expected_url: str | None, current_url: str | None) -> bool:
    """Detect whether a navigation was redirected to an auth wall."""
    if not current_url:
        return False
    expected_is_auth = is_auth_url(expected_url)
    current_is_auth = is_auth_url(current_url)
    return current_is_auth and not expected_is_auth


async def find_submit_button(page: Any, password_input: Any = None, event_recorder: Any | None = None) -> Any:
    """Locate the authentic form submit button, avoiding OAuth/SSO buttons."""
    # 1. Semantic submit selectors first
    semantic_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button[form]',
        'button[data-action="submit"]',
        'button[data-testid*="submit" i]',
        'button[data-testid*="login" i]',
        'button[data-testid*="signin" i]',
    ]

    for sel in semantic_selectors:
        try:
            buttons = page.locator(sel)
            count = buttons.count()
            if inspect.isawaitable(count):
                count = await count
            for i in range(count):
                btn = buttons.nth(i)
                vis = btn.is_visible(timeout=300)
                if inspect.isawaitable(vis):
                    vis = await vis
                if not vis:
                    continue
                txt_call = btn.inner_text(timeout=300)
                txt = (await txt_call if inspect.isawaitable(txt_call) else txt_call) or ""
                if any(oa in txt.lower() for oa in OAUTH_KEYWORDS):
                    continue
                return btn
        except Exception:
            continue

    # 2. Check within ancestor form of password_input if provided
    if password_input is not None:
        try:
            form = password_input.locator("xpath=ancestor::form").first
            form_count = form.count()
            if inspect.isawaitable(form_count):
                form_count = await form_count
            if form_count > 0:
                for sel in ['button[type="submit"]', 'input[type="submit"]', 'button']:
                    btns = form.locator(sel)
                    cnt = btns.count()
                    if inspect.isawaitable(cnt):
                        cnt = await cnt
                    for i in range(cnt):
                        b = btns.nth(i)
                        vis = b.is_visible(timeout=300)
                        if inspect.isawaitable(vis):
                            vis = await vis
                        if not vis:
                            continue
                        txt_call = b.inner_text(timeout=300)
                        txt = (await txt_call if inspect.isawaitable(txt_call) else txt_call) or ""
                        if any(oa in txt.lower() for oa in OAUTH_KEYWORDS):
                            continue
                        return b
        except Exception:
            pass

    # 3. Levenshtein text matching against observed visible buttons
    try:
        all_buttons = page.locator('button, [role="button"], input[type="button"], a[role="button"]')
        cnt = all_buttons.count()
        if inspect.isawaitable(cnt):
            cnt = await cnt
        for i in range(cnt):
            btn = all_buttons.nth(i)
            vis = btn.is_visible(timeout=300)
            if inspect.isawaitable(vis):
                vis = await vis
            if not vis:
                continue
            txt_call = btn.inner_text(timeout=300)
            txt = (await txt_call if inspect.isawaitable(txt_call) else txt_call) or ""
            lower = txt.strip().lower()
            if not lower or any(oa in lower for oa in OAUTH_KEYWORDS):
                continue
            # Exact or distance <= 2 match
            if any(_levenshtein_distance(lower, target) <= 2 or target in lower for target in COMMON_SUBMIT_TERMS):
                return btn
    except Exception:
        pass

    # 4. Fallback: query AI Reasoner if provider is available
    try:
        from app.engine.ai.settings import ai_settings
        if ai_settings.ai_enabled:
            from app.engine.ai.provider import get_ai_provider
            from app.engine.ai.reasoner import AgentReasoner
            from app.engine.ai.validator import validate_action
            provider = get_ai_provider()
            if provider:
                reasoner = AgentReasoner(provider)
                observer = None
                if hasattr(page, "observe"):
                    obs = await page.observe()
                else:
                    from app.engine.browser.observer import PageObserver
                    obs = await PageObserver(page).observe()
                proposed_selector = await reasoner.propose_submit_button(obs)
                if proposed_selector and validate_action({"type": "click", "target": {"css": proposed_selector}}):
                    proposed_btn = page.locator(proposed_selector).first
                    vis = proposed_btn.is_visible(timeout=500)
                    if inspect.isawaitable(vis):
                        vis = await vis
                    if event_recorder:
                        try:
                            from app.modules.executions.event_types import EventTypes
                            res = event_recorder(EventTypes.AI_PROPOSAL, {
                                "stage": "submit_button",
                                "selector": proposed_selector,
                                "accepted": bool(vis),
                            })
                            if inspect.isawaitable(res):
                                await res
                            if vis:
                                res2 = event_recorder(EventTypes.AI_ASSISTED, {
                                    "stage": "submit_button",
                                    "selector": proposed_selector,
                                    "message": "AI successfully identified submit button",
                                })
                                if inspect.isawaitable(res2):
                                    await res2
                        except Exception as ev_err:
                            logger.debug("Failed recording AI events in find_submit_button: %s", ev_err)
                    if vis:
                        return proposed_btn

    except Exception as e:
        logger.debug("AI propose_submit_button fallback failed: %s", e)

    return None


async def locate_auth_input_element(page_or_frame: Any, selector: str, timeout: int = 1000) -> Any | None:
    """Locate a visible input element within a page or frame."""
    try:
        loc = page_or_frame.locator(selector).first
        if await loc.is_visible(timeout=timeout):
            return loc
    except Exception:
        pass
    return None


async def find_auth_inputs_across_frames(page: Any) -> tuple[Any | None, Any | None, Any | None, Any]:
    """Finds name, email, and password inputs across main page and all child frames.

    Returns (name_input, email_input, password_input, active_frame_or_page).
    """
    frames = [page]
    try:
        page_frames = getattr(page, "frames", [])
        for f in page_frames:
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

    for scope in frames:
        email_input = await locate_auth_input_element(scope, email_selector, timeout=800)
        password_input = await locate_auth_input_element(scope, password_selector, timeout=800)

        if not email_input:
            email_input = await locate_auth_input_element(scope, fallback_email_selector, timeout=500)

        if email_input or password_input:
            name_input = await locate_auth_input_element(scope, name_selector, timeout=400)
            return name_input, email_input, password_input, scope

    return None, None, None, page


async def find_auth_entrance_semantically(
    page: Any,
    provider: Any = None,
    is_signup: bool = False,
    event_recorder: Any | None = None,
) -> bool:
    """Inspects the page for interactive entrance elements and uses AI or heuristics to open auth."""
    extract_entrance_script = """
    () => {
        const candidates = [];
        const elements = Array.from(document.querySelectorAll('a, button, [role="button"], input[type="button"], input[type="submit"]'));
        let idx = 0;
        for (const el of elements) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
            if (rect.width <= 0 || rect.height <= 0) continue;

            const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
            if (!text && !el.getAttribute('href')) continue;

            el.setAttribute('data-kova-entrance-candidate', String(idx));
            candidates.push({
                index: idx,
                tagName: el.tagName.toLowerCase(),
                text: text.slice(0, 80),
                href: el.getAttribute('href') || '',
                role: el.getAttribute('role') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
            });
            idx++;
            if (candidates.length >= 60) break;
        }
        return candidates;
    }
    """
    try:
        candidates = await page.evaluate(extract_entrance_script)
        if not candidates:
            return False

        ai_prov = provider
        if ai_prov is None:
            try:
                from app.engine.ai.provider import get_ai_provider
                ai_prov = get_ai_provider()
            except Exception:
                ai_prov = None

        chosen_idx = None
        if ai_prov:
            try:
                from app.engine.ai.reasoner import AgentReasoner
                reasoner = AgentReasoner(ai_prov)
                current_url = getattr(page, "url", "")
                result = await reasoner.identify_auth_entrance(current_url, candidates, is_signup=is_signup)
                if result and result.entrance_index is not None:
                    chosen_idx = result.entrance_index
                    if event_recorder:
                        try:
                            from app.modules.executions.event_types import EventTypes
                            res = event_recorder(EventTypes.AI_PROPOSAL, {
                                "stage": "auth_entrance",
                                "current_url": current_url,
                                "entrance_index": chosen_idx,
                                "is_signup": is_signup,
                                "accepted": True,
                            })
                            if inspect.isawaitable(res):
                                await res
                            res2 = event_recorder(EventTypes.AI_ASSISTED, {
                                "stage": "auth_entrance",
                                "current_url": current_url,
                                "entrance_index": chosen_idx,
                                "message": f"AI identified {'signup' if is_signup else 'signin'} entrance link",
                            })
                            if inspect.isawaitable(res2):
                                await res2
                        except Exception as emit_err:
                            logger.debug("Failed emitting AI proposal event: %s", emit_err)
            except Exception as ex:
                logger.debug("AI auth entrance error: %s", ex)


        if chosen_idx is None:
            keywords = (
                ["sign up", "signup", "create account", "register", "get started", "start free", "join", "start learning", "try for free"]
                if is_signup else
                ["sign in", "signin", "log in", "login", "my account", "enter", "portal"]
            )
            for c in candidates:
                blob = f"{c['text']} {c['href']} {c['ariaLabel']}".lower()
                if any(kw in blob for kw in keywords):
                    chosen_idx = c["index"]
                    break

        if chosen_idx is not None:
            cand = next((c for c in candidates if c["index"] == chosen_idx), None)
            if cand and cand.get("href") and cand["href"].startswith("/"):
                parsed = urlparse(getattr(page, "url", ""))
                target = f"{parsed.scheme}://{parsed.netloc}{cand['href']}"
                await page.goto(target, wait_until="domcontentloaded", timeout=5000)
                await asyncio.sleep(1.0)
                return True

            target_loc = page.locator(f'[data-kova-entrance-candidate="{chosen_idx}"]').first
            if await target_loc.is_visible(timeout=1000):
                await target_loc.click(timeout=2000)
                await asyncio.sleep(1.0)
                return True
    except Exception as e:
        logger.debug("find_auth_entrance_semantically error: %s", e)

    return False


async def open_auth_view_if_needed(page: Any, is_signup: bool = False, provider: Any = None, event_recorder: Any | None = None) -> bool:
    """Attempts to reveal or navigate to login/signup modal or page if inputs are missing."""
    if is_signup:
        button_selectors = [
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
        button_selectors = [
            'a:has-text("Sign in")', 'button:has-text("Sign in")',
            'a:has-text("Sign In")', 'button:has-text("Sign In")',
            'a:has-text("Log in")', 'button:has-text("Log in")',
            'a:has-text("Log In")', 'button:has-text("Log In")',
            'a:has-text("Login")', 'button:has-text("Login")',
            'a:has-text("Account")', 'button:has-text("Account")',
            'a[href*="signin" i]', 'a[href*="login" i]', 'a[href*="sign-in" i]', 'a[href*="log-in" i]',
        ]
        fallback_paths = ["/auth/signin", "/auth/login", "/login", "/signin", "/sign-in"]

    # 1. Try finding and clicking button/link on the page
    for sel in button_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=600):
                await loc.click(timeout=1500)
                await asyncio.sleep(1.0)
                return True
        except Exception:
            continue

    # 2. Try direct navigation to standard paths if still on base page
    current_url = getattr(page, "url", "")
    if current_url:
        parsed = urlparse(current_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in fallback_paths:
            try:
                target_url = f"{base}{path}"
                resp = await page.request.get(target_url, timeout=2000, fail_on_status_code=False)
                if 200 <= resp.status < 400:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=4000)
                    await asyncio.sleep(1.0)
                    return True
            except Exception:
                continue

    # 3. AI / semantic entrance element fallback
    return await find_auth_entrance_semantically(page, provider=provider, is_signup=is_signup, event_recorder=event_recorder)



async def find_auth_inputs_semantically(
    page: Any,
    provider: Any = None,
    is_signup: bool = False,
    event_recorder: Any | None = None,
) -> tuple[Any | None, Any | None, Any | None, Any]:
    """Inspects the page for visible input/button elements and uses AI or semantic heuristics to find fields."""
    frames = [page]
    try:
        page_frames = getattr(page, "frames", [])
        for f in page_frames:
            if f not in frames:
                frames.append(f)
    except Exception:
        pass

    extract_script = """
    () => {
        const candidates = [];
        // Extract form inputs and editable textboxes before generic buttons to prevent navbar starvation
        const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, [contenteditable="true"], [role="textbox"]'));
        const buttons = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
        const elements = [...inputs, ...buttons];
        let idx = 0;
        for (const el of elements) {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
            if (rect.width <= 0 || rect.height <= 0) continue;

            let labelText = '';
            if (el.id) {
                const lbl = document.querySelector(`label[for="${el.id}"]`);
                if (lbl) labelText = lbl.innerText.trim();
            }
            if (!labelText && el.getAttribute('aria-labelledby')) {
                const albl = document.getElementById(el.getAttribute('aria-labelledby'));
                if (albl) labelText = albl.innerText.trim();
            }
            if (!labelText && el.closest('label')) {
                labelText = el.closest('label').innerText.trim();
            }
            if (!labelText) {
                const parent = el.closest('.form-item, .form-group, .field, fieldset, [class*="input" i], [class*="field" i], div');
                if (parent) {
                    const plbl = parent.querySelector('label, [class*="label" i], span, p');
                    if (plbl && plbl !== el) labelText = plbl.innerText.trim();
                }
            }
            if (!labelText && el.previousElementSibling && ['LABEL', 'SPAN', 'P'].includes(el.previousElementSibling.tagName)) {
                labelText = el.previousElementSibling.innerText.trim();
            }

            el.setAttribute('data-kova-auth-candidate', String(idx));
            candidates.push({
                index: idx,
                tagName: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '',
                id: el.getAttribute('id') || '',
                placeholder: el.getAttribute('placeholder') || '',
                ariaLabel: el.getAttribute('aria-label') || '',
                labelText: labelText.slice(0, 100),
                role: el.getAttribute('role') || '',
                text: (el.innerText || el.value || '').trim().slice(0, 100),
            });
            idx++;
            if (candidates.length >= 60) break;
        }
        return candidates;
    }
    """

    for scope in frames:
        try:
            candidates = await scope.evaluate(extract_script)
            if not candidates:
                continue

            # Try AI provider if available
            ai_prov = provider
            if ai_prov is None:
                try:
                    from app.engine.ai.provider import get_ai_provider
                    ai_prov = get_ai_provider()
                except Exception:
                    ai_prov = None

            result = None
            if ai_prov:
                try:
                    from app.engine.ai.reasoner import AgentReasoner
                    reasoner = AgentReasoner(ai_prov)
                    current_url = getattr(page, "url", "")
                    result = await reasoner.identify_auth_elements(current_url, candidates, is_signup=is_signup)
                    if result and (result.email_or_user_index is not None or result.password_index is not None):
                        if event_recorder:
                            try:
                                from app.modules.executions.event_types import EventTypes
                                res = event_recorder(EventTypes.AI_PROPOSAL, {
                                    "stage": "auth_elements",
                                    "current_url": current_url,
                                    "email_index": result.email_or_user_index,
                                    "password_index": result.password_index,
                                    "is_signup": is_signup,
                                    "accepted": True,
                                })
                                if inspect.isawaitable(res):
                                    await res
                                res2 = event_recorder(EventTypes.AI_ASSISTED, {
                                    "stage": "auth_elements",
                                    "current_url": current_url,
                                    "message": "AI identified auth form inputs",
                                })
                                if inspect.isawaitable(res2):
                                    await res2
                            except Exception as emit_err:
                                logger.debug("Failed emitting AI proposal event: %s", emit_err)
                except Exception as ex:
                    logger.debug("AI reasoner auth input identification error: %s", ex)

            email_idx = result.email_or_user_index if result else None
            pwd_idx = result.password_index if result else None
            name_idx = result.name_index if result else None


            # Resilient fallback if AI is unavailable or didn't match
            if email_idx is None or pwd_idx is None:
                # Pass 1: standard keyword search in candidate metadata
                for c in candidates:
                    idx = c["index"]
                    if c["tagName"] == "button" and c.get("type") != "submit":
                        continue
                    text_blob = f"{c['type']} {c['name']} {c['id']} {c['placeholder']} {c['ariaLabel']} {c['labelText']}".lower()
                    if pwd_idx is None and ("password" in text_blob or "pass" in text_blob or c["type"] == "password" or "pin" in text_blob or "secret" in text_blob):
                        pwd_idx = idx
                    elif email_idx is None and (any(k in text_blob for k in ["email", "user", "identifier", "login", "phone", "account"]) or "@" in c.get("placeholder", "")):
                        email_idx = idx
                    elif name_idx is None and is_signup and any(k in text_blob for k in ["fullname", "full_name", "first name", "name"]):
                        name_idx = idx

                # Pass 2: structural pairing (if password field identified, preceding text input is identifier)
                if pwd_idx is not None and email_idx is None:
                    for c in candidates:
                        if c["index"] < pwd_idx and c["tagName"] in ("input", "textarea") and c.get("type") not in ("password", "hidden", "checkbox", "radio", "submit"):
                            email_idx = c["index"]
                            break

                # Pass 3: layout pairing (if exactly two non-button inputs exist on page/form, input 0 is email, input 1 is password)
                if email_idx is None or pwd_idx is None:
                    text_inputs = [c for c in candidates if c["tagName"] in ("input", "textarea") and c.get("type") not in ("hidden", "checkbox", "radio", "submit")]
                    if len(text_inputs) >= 2:
                        if email_idx is None:
                            email_idx = text_inputs[0]["index"]
                        if pwd_idx is None and text_inputs[1]["index"] != email_idx:
                            pwd_idx = text_inputs[1]["index"]
                    elif len(text_inputs) == 1 and email_idx is None:
                        email_idx = text_inputs[0]["index"]

            email_loc = scope.locator(f'[data-kova-auth-candidate="{email_idx}"]').first if email_idx is not None else None
            pwd_loc = scope.locator(f'[data-kova-auth-candidate="{pwd_idx}"]').first if pwd_idx is not None else None
            name_loc = scope.locator(f'[data-kova-auth-candidate="{name_idx}"]').first if name_idx is not None else None

            if email_loc or pwd_loc:
                return name_loc, email_loc, pwd_loc, scope
        except Exception as e:
            logger.debug("Semantic auth input extraction failed in scope: %s", e)

    return None, None, None, page


async def perform_login(
    page: Any,
    email: str,
    password: str,
    name: str | None = None,
    is_signup: bool = False,
    provider: Any = None,
    event_recorder: Any | None = None,
) -> tuple[bool, str]:
    """Fill login or registration form, submit credentials, and wait for session.

    Handles React/SPA controlled inputs by dispatching synthetic change events,
    auto-checks terms checkboxes, and handles form submission.
    """
    if not email or not password:
        return False, "Missing email or password credentials."

    initial_url = getattr(page, "url", "")
    current_url_lower = initial_url.lower()

    # If registration is requested, check if we are currently on a sign-in view
    # (e.g. redirected to /signin or /login). If so, switch to signup view first.
    if is_signup:
        is_on_signin_path = any(p in current_url_lower for p in ["/signin", "/login", "/sign-in", "/log-in"])
        if is_on_signin_path:
            logger.info("is_signup requested on signin URL (%s), navigating to signup view", initial_url)
            opened = await open_auth_view_if_needed(page, is_signup=True, provider=provider, event_recorder=event_recorder)
            if opened:
                logger.info("Successfully opened signup view, new URL: %s", getattr(page, "url", ""))

    # Locate inputs across page and any frames
    name_input, email_input, password_input, active_scope = await find_auth_inputs_across_frames(page)

    # If inputs are not found on current page, attempt to open auth modal or navigate to auth route
    if not email_input or not password_input:
        opened = await open_auth_view_if_needed(page, is_signup=is_signup, provider=provider, event_recorder=event_recorder)
        if opened:
            name_input, email_input, password_input, active_scope = await find_auth_inputs_across_frames(page)

    # If registration is requested but inputs found belong to a login form (e.g. button says "Sign in"), switch view
    if is_signup and (email_input or password_input):
        submit_btn = await find_submit_button(active_scope or page, event_recorder=event_recorder)
        submit_txt = ""
        if submit_btn:
            try:
                submit_txt = (await submit_btn.inner_text(timeout=300) or "").strip().lower()
            except Exception:
                pass
        if submit_txt and any(k in submit_txt for k in ["sign in", "log in", "login"]) and not any(k in submit_txt for k in ["sign up", "signup", "create", "register"]):
            logger.info("Submit button '%s' indicates signin view but is_signup=True. Attempting switch to signup view.", submit_txt)
            opened = await open_auth_view_if_needed(page, is_signup=True, provider=provider, event_recorder=event_recorder)
            if opened:
                name_input, email_input, password_input, active_scope = await find_auth_inputs_across_frames(page)

    # Semantic AI fallback if heuristic selectors failed to locate input fields
    if not email_input or not password_input:
        s_name, s_email, s_pwd, s_scope = await find_auth_inputs_semantically(
            page, provider=provider, is_signup=is_signup, event_recorder=event_recorder
        )

        if s_email or s_pwd:
            name_input = name_input or s_name
            email_input = email_input or s_email
            password_input = password_input or s_pwd
            active_scope = s_scope or active_scope

    # Multi-step authentication: email entered on step 1, password appears on step 2
    if email_input and not password_input:
        try:
            await email_input.focus()
            await email_input.fill(email)
            await email_input.evaluate(
                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
            next_btn = await find_submit_button(active_scope or page)
            if next_btn:
                await next_btn.click(timeout=2000)
                await asyncio.sleep(1.0)
                _, _, password_input, active_scope = await find_auth_inputs_across_frames(page)
                if not password_input:
                    _, _, password_input, active_scope = await find_auth_inputs_semantically(
                        page, provider=provider, is_signup=is_signup
                    )
        except Exception as ex:
            logger.debug("Multi-step email submit attempt: %s", ex)

    if name_input:
        try:
            display_name = name or "Kova Tester"
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
        return False, "Could not find email input field on the page."
    if not password_input:
        current_url = getattr(page, "url", "").lower()
        if not is_auth_url(current_url) or current_url != initial_url.lower():
            return True, ""
        try:
            body_text = (await page.inner_text("body", timeout=1000) or "").lower()
            if any(term in body_text for term in ["check your email", "magic link", "verification link", "verification email", "we sent a link"]):
                return True, "Verification email or magic link dispatched."
        except Exception:
            pass
        return False, "Could not find password input field on the page."

    try:
        # Focus and fill email
        await email_input.focus()
        await email_input.fill(email)
        try:
            await email_input.evaluate(
                "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
            )
        except Exception:
            pass

        # Focus and fill password (handles repeat password / confirm password if present)
        try:
            target_scope = active_scope or page
            pwd_locs = await target_scope.locator('input[type="password"], input[name*="pass" i]').all()
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
            if password_input:
                await password_input.focus()
                await password_input.fill(password)
                try:
                    await password_input.evaluate(
                        "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                    )
                except Exception:
                    pass

        # Agree to terms if checkbox exists
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

        await asyncio.sleep(0.3)

        # Submit form
        submit_btn = await find_submit_button(page, password_input, event_recorder=event_recorder)
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

        if not submitted:
            # Fallback: press Enter on password field
            try:
                await password_input.press("Enter")
                submitted = True
            except Exception:
                pass

        if not submitted:
            return False, "Could not submit login form (no active submit button found)."

        # Wait for navigation, error banner, or form dismissal (up to 15 seconds for cold-start backends)
        error_locators = [
            '[role="alert"]',
            '.error-message',
            '.alert-error',
            '.toast',
            '[role="status"]',
            '.text-destructive',
            '.text-red-500',
            '*:has-text("Incorrect email or password")',
            '*:has-text("Invalid credentials")',
            '*:has-text("incorrect password")',
            '*:has-text("User not found")',
        ]
        error_phrases = [
            "incorrect email or password",
            "invalid email or password",
            "invalid credentials",
            "user not found",
            "account does not exist",
            "password is wrong",
            "incorrect password",
        ]
        cold_start_phrases = [
            "waking up",
            "cold start",
            "render",
            "first load",
            "spinning up",
            "please wait",
            "connecting",
            "starting server",
        ]

        max_iterations = 60  # Default 30s
        for iteration in range(90):  # Up to 45 seconds if cold-start detected
            await asyncio.sleep(0.5)
            curr = getattr(page, "url", "")
            if curr != initial_url and not is_auth_url(curr):
                return True, f"Authentication succeeded, redirected to {curr}"

            # Check if explicit error locator is visible
            for el_sel in error_locators:
                try:
                    err_el = page.locator(el_sel).first
                    if await err_el.is_visible(timeout=150):
                        err_txt = await err_el.inner_text(timeout=150)
                        if err_txt and len(err_txt.strip()) > 3:
                            return False, f"Login rejected by application: {err_txt.strip()}"
                except Exception:
                    pass

            # Check page body for error phrases or cold-start notice
            try:
                b_txt = (await page.inner_text("body", timeout=150) or "").lower()
                for phrase in error_phrases:
                    if phrase in b_txt:
                        return False, f"Login rejected by application: {phrase.capitalize()}"
                if any(csp in b_txt for csp in cold_start_phrases):
                    max_iterations = 90
            except Exception:
                pass

            # Check if password input has disappeared (SPA state change / modal dismiss)
            try:
                if await page.locator('input[type="password"]').count() == 0:
                    return True, "Authentication succeeded (login form dismissed)."
            except Exception:
                pass

            if iteration >= max_iterations:
                break

        # Evidence-based failure diagnosis and bounded recovery
        diagnosis = await diagnose_auth_failure(
            page,
            is_signup=is_signup,
            initial_url=initial_url,
            credential={"email": email, "password": password, "name": name},
        )
        if diagnosis.category == AuthFailureCategory.ACCOUNT_ALREADY_CREATED:
            return True, diagnosis.detail
        if diagnosis.can_retry_autonomously:
            recovered, rec_detail = await attempt_registration_recovery(
                page,
                diagnosis,
                credential={"email": email, "password": password, "name": name},
            )
            if recovered:
                return True, rec_detail
            return False, rec_detail

        return False, diagnosis.detail

    except Exception as e:
        logger.warning("perform_login failed with exception: %s", e)
        return False, f"Error during login: {str(e)[:150]}"


async def diagnose_auth_failure(
    page: Any,
    is_signup: bool = False,
    initial_url: str = "",
    credential: dict | None = None,
    network_errors: list[dict] | None = None,
) -> AuthFailureDiagnosis:
    """Inspects the browser state and live DOM after an auth or registration submission.

    Produces a concrete, evidence-based diagnostic distinguishing client validation,
    missing required/custom fields, consent barriers, CAPTCHA challenges, server rejections,
    email verification, rate limiting, and unknown states.
    """
    credential = credential or {}
    evidence: dict[str, Any] = {
        "initial_url": initial_url,
        "current_url": getattr(page, "url", ""),
        "is_signup": is_signup,
    }

    # 1. Check network errors / responses if available
    if network_errors:
        for net_err in network_errors:
            status = net_err.get("status")
            if status == 429:
                return AuthFailureDiagnosis(
                    category=AuthFailureCategory.RATE_LIMITED,
                    detail="Server responded with HTTP 429 (Too Many Requests / Rate Limited).",
                    can_retry_autonomously=False,
                    recommended_recovery_action="continue_public_exploration",
                    evidence={**evidence, "network_error": net_err},
                )
            elif status in (400, 422):
                msg = net_err.get("body") or net_err.get("message") or f"HTTP {status}"
                return AuthFailureDiagnosis(
                    category=AuthFailureCategory.SERVER_REJECTION,
                    detail=f"Server rejected submission with HTTP {status}: {msg}",
                    server_error=msg,
                    can_retry_autonomously=False,
                    recommended_recovery_action="continue_public_exploration",
                    evidence={**evidence, "network_error": net_err},
                )

    # 2. In-browser DOM and form evaluation
    dom_data = {}
    try:
        if hasattr(page, "evaluate"):
            eval_result = await page.evaluate("""
                () => {
                    const fields = [];
                    const invalidFields = [];
                    const unfilledRequired = [];
                    const consentRequired = [];
                    let captchaDetected = false;
                    let emailVerificationDetected = false;
                    let serverError = null;

                    // 1. CAPTCHA detection
                    const captchaSelectors = [
                        'iframe[src*="recaptcha"]',
                        'iframe[src*="hcaptcha"]',
                        'iframe[src*="challenges.cloudflare.com"]',
                        'iframe[src*="turnstile"]',
                        '.g-recaptcha',
                        '.h-captcha',
                        '#cf-turnstile',
                        '[data-sitekey]'
                    ];
                    for (const sel of captchaSelectors) {
                        try {
                            const el = document.querySelector(sel);
                            if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.tagName === 'IFRAME')) {
                                captchaDetected = true;
                                break;
                            }
                        } catch (e) {}
                    }

                    // 2. Form input examination
                    const inputs = Array.from(document.querySelectorAll('input, select, textarea'));
                    for (const el of inputs) {
                        try {
                            const type = (el.type || 'text').toLowerCase();
                            if (['hidden', 'submit', 'button', 'reset', 'image'].includes(type)) continue;

                            const name = (el.name || el.id || el.getAttribute('aria-label') || '').toLowerCase();
                            const labelEl = el.id ? document.querySelector(`label[for="${el.id}"]`) : el.closest('label');
                            const labelText = (labelEl?.innerText || el.placeholder || el.getAttribute('aria-label') || name || '').trim();
                            const isRequired = el.required || el.getAttribute('aria-required') === 'true';
                            const val = el.value || '';
                            const isChecked = el.checked;

                            const isInvalid = el.getAttribute('aria-invalid') === 'true' || (el.validity && !el.validity.valid);
                            const validationMsg = el.validationMessage || '';

                            let inlineError = '';
                            const parent = el.parentElement;
                            if (parent) {
                                const errEl = parent.querySelector('.error, .invalid-feedback, .text-destructive, [role="alert"], [class*="error"]');
                                if (errEl && errEl.innerText) {
                                    inlineError = errEl.innerText.trim();
                                }
                            }

                            const fieldInfo = {
                                type,
                                name: el.name || el.id || '',
                                label: labelText,
                                required: isRequired,
                                isEmpty: type === 'checkbox' || type === 'radio' ? !isChecked : !val.trim(),
                                isInvalid,
                                validationMessage: validationMsg || inlineError,
                            };
                            fields.push(fieldInfo);

                            if (isRequired && fieldInfo.isEmpty) {
                                if (type === 'checkbox') {
                                    consentRequired.push(labelText || name || 'Terms / Consent');
                                } else {
                                    unfilledRequired.push({ name: fieldInfo.name, label: labelText, type });
                                }
                            } else if (isInvalid || inlineError) {
                                invalidFields.push({ name: fieldInfo.name, label: labelText, error: validationMsg || inlineError });
                            }
                        } catch (e) {}
                    }

                    // 3. Visible alert banners
                    const alertSelectors = [
                        '[role="alert"]',
                        '.alert-error',
                        '.alert-danger',
                        '.alert',
                        '.error-message',
                        '.toast',
                        '[aria-live="polite"]',
                        '[aria-live="assertive"]',
                        '.text-destructive',
                        '.text-red-500',
                        '.text-red-600'
                    ];
                    for (const sel of alertSelectors) {
                        try {
                            const els = document.querySelectorAll(sel);
                            for (const el of els) {
                                if (el.offsetWidth > 0 || el.offsetHeight > 0) {
                                    const txt = (el.innerText || '').trim();
                                    if (txt.length >= 4) {
                                        serverError = txt.slice(0, 300);
                                        break;
                                    }
                                }
                            }
                            if (serverError) break;
                        } catch (e) {}
                    }

                    // 4. Verification phrases in body text
                    try {
                        const bodyText = (document.body ? document.body.innerText : '').toLowerCase();
                        const verificationPhrases = [
                            'check your email',
                            'verification link',
                            'we sent a verification link',
                            'we sent a code',
                            'confirm your email',
                            'verification email sent',
                            'verify your account',
                            'magic link sent'
                        ];
                        for (const phrase of verificationPhrases) {
                            if (bodyText.includes(phrase)) {
                                emailVerificationDetected = true;
                                break;
                            }
                        }
                    } catch (e) {}

                    return {
                        fields,
                        invalidFields,
                        unfilledRequired,
                        consentRequired,
                        captchaDetected,
                        emailVerificationDetected,
                        serverError,
                        currentUrl: window.location.href,
                        pageTitle: document.title
                    };
                }
            """)
            if isinstance(eval_result, dict):
                dom_data = eval_result
    except Exception as e:
        logger.debug("diagnose_auth_failure DOM evaluation error: %s", e)

    evidence["dom_data"] = dom_data

    # Check for body-level verification signals if not already detected
    if not dom_data.get("emailVerificationDetected") and hasattr(page, "inner_text"):
        try:
            b_txt = (await page.inner_text("body", timeout=500) or "").lower()
            if any(term in b_txt for term in ["check your email", "verification email", "we sent a link", "verify your account"]):
                dom_data["emailVerificationDetected"] = True
        except Exception:
            pass

    # Check if URL or title changed to dashboard/app (Account actually created!)
    curr_url = getattr(page, "url", "").lower()
    if curr_url and not is_auth_url(curr_url) and curr_url != initial_url.lower():
        return AuthFailureDiagnosis(
            category=AuthFailureCategory.ACCOUNT_ALREADY_CREATED,
            detail=f"Account created successfully; application navigated to {curr_url}.",
            can_retry_autonomously=False,
            recommended_recovery_action=None,
            evidence=evidence,
        )

    if dom_data.get("emailVerificationDetected"):
        return AuthFailureDiagnosis(
            category=AuthFailureCategory.EMAIL_VERIFICATION_REQUIRED,
            detail="Registration initiated; application requires email verification or confirmation link.",
            email_verification_detected=True,
            can_retry_autonomously=False,
            recommended_recovery_action="check_email",
            evidence=evidence,
        )

    if dom_data.get("captchaDetected"):
        return AuthFailureDiagnosis(
            category=AuthFailureCategory.CAPTCHA_REQUIRED,
            detail="Registration is blocked by CAPTCHA challenge or bot protection.",
            captcha_detected=True,
            can_retry_autonomously=False,
            recommended_recovery_action="request_human",
            evidence=evidence,
        )

    consent_req = dom_data.get("consentRequired") or []
    if consent_req:
        return AuthFailureDiagnosis(
            category=AuthFailureCategory.REQUIRED_CONSENT,
            detail=f"Registration requires explicit consent: {', '.join(consent_req)}.",
            consent_required=consent_req,
            can_retry_autonomously=True,
            recommended_recovery_action="check_consent",
            evidence=evidence,
        )

    unfilled = dom_data.get("unfilledRequired") or []
    if unfilled:
        missing_labels = [f.get("label") or f.get("name") for f in unfilled if f.get("name") or f.get("label")]
        unfilled_names = [f.get("name", "").lower() for f in unfilled]
        is_custom = any(k not in ("email", "password", "name", "username") for k in unfilled_names)
        category = AuthFailureCategory.CUSTOM_FIELDS_REQUIRED if is_custom else AuthFailureCategory.CLIENT_VALIDATION
        can_auto_recover = any(
            any(cand in k for cand in ("first", "last", "confirm", "phone"))
            for k in unfilled_names
        )
        return AuthFailureDiagnosis(
            category=category,
            detail=f"Registration form has required fields not filled: {', '.join(missing_labels)}.",
            missing_fields=missing_labels,
            unfilled_required_fields=unfilled,
            can_retry_autonomously=can_auto_recover,
            recommended_recovery_action="fill_missing_fields" if can_auto_recover else "continue_public_exploration",
            evidence=evidence,
        )

    invalid_fields = dom_data.get("invalidFields") or []
    if invalid_fields:
        inv_summary = [f"{f.get('label') or f.get('name')}: {f.get('error')}" for f in invalid_fields]
        return AuthFailureDiagnosis(
            category=AuthFailureCategory.CLIENT_VALIDATION,
            detail=f"Form validation errors detected: {'; '.join(inv_summary)}.",
            invalid_fields=invalid_fields,
            can_retry_autonomously=False,
            recommended_recovery_action="continue_public_exploration",
            evidence=evidence,
        )

    server_err = dom_data.get("serverError")
    if server_err:
        return AuthFailureDiagnosis(
            category=AuthFailureCategory.SERVER_REJECTION,
            detail=f"Server rejected registration: {server_err}",
            server_error=server_err,
            can_retry_autonomously=False,
            recommended_recovery_action="continue_public_exploration",
            evidence=evidence,
        )

    return AuthFailureDiagnosis(
        category=AuthFailureCategory.UNKNOWN,
        detail=f"Registration did not complete: browser remained on {curr_url or initial_url} without explicit error banner or redirect.",
        can_retry_autonomously=False,
        recommended_recovery_action="continue_public_exploration",
        evidence=evidence,
    )


async def attempt_registration_recovery(
    page: Any,
    diagnosis: AuthFailureDiagnosis,
    credential: dict,
) -> tuple[bool, str]:
    """Attempt autonomous recovery for safely identifiable input errors."""
    if not diagnosis.can_retry_autonomously:
        return False, diagnosis.detail

    password = credential.get("password", "")
    email = credential.get("email", "")
    recovered_any = False

    try:
        # 1. Recover consent
        if diagnosis.consent_required:
            terms_selector = (
                'input[type="checkbox"][name*="term" i], '
                'input[type="checkbox"][name*="agree" i], '
                'input[type="checkbox"][id*="term" i], '
                'input[type="checkbox"][id*="agree" i], '
                'input[type="checkbox"][aria-label*="term" i], '
                'input[type="checkbox"][aria-label*="agree" i], '
                'input[type="checkbox"][required]'
            )
            cbs = await page.locator(terms_selector).all()
            for cb in cbs:
                try:
                    if await cb.is_visible(timeout=300) and not await cb.is_checked():
                        await cb.check()
                        recovered_any = True
                except Exception:
                    pass

        # 2. Recover missing required fields
        for field_info in diagnosis.unfilled_required_fields:
            fname = field_info.get("name", "").lower()
            flabel = field_info.get("label", "").lower()
            # Confirm password
            if "confirm" in fname or "confirm" in flabel or "repeat" in fname or "confirmation" in fname:
                try:
                    loc = page.locator(f'input[name="{field_info.get("name")}"]').first
                    if await loc.is_visible(timeout=500):
                        await loc.fill(password)
                        recovered_any = True
                except Exception:
                    pass
            # Split name (first name / last name)
            elif "first" in fname or "first" in flabel:
                try:
                    loc = page.locator(f'input[name="{field_info.get("name")}"]').first
                    if await loc.is_visible(timeout=500):
                        await loc.fill("Kova")
                        recovered_any = True
                except Exception:
                    pass
            elif "last" in fname or "last" in flabel:
                try:
                    loc = page.locator(f'input[name="{field_info.get("name")}"]').first
                    if await loc.is_visible(timeout=500):
                        await loc.fill("Tester")
                        recovered_any = True
                except Exception:
                    pass
            # Phone number
            elif "phone" in fname or "phone" in flabel or "mobile" in fname:
                try:
                    loc = page.locator(f'input[name="{field_info.get("name")}"]').first
                    if await loc.is_visible(timeout=500):
                        await loc.fill("+2348012345678")
                        recovered_any = True
                except Exception:
                    pass

        if not recovered_any:
            return False, diagnosis.detail

        # Click submit button again
        submit_btn = await find_submit_button(page)
        if submit_btn:
            await submit_btn.click(timeout=3000)
            await asyncio.sleep(2.0)
            # Check if navigated away
            curr_url = getattr(page, "url", "").lower()
            if not is_auth_url(curr_url):
                return True, f"Registration recovery succeeded; navigated to {curr_url}."

        # Re-diagnose
        new_diag = await diagnose_auth_failure(page, is_signup=True, initial_url=diagnosis.evidence.get("initial_url", ""), credential=credential)
        if new_diag.category == AuthFailureCategory.ACCOUNT_ALREADY_CREATED:
            return True, new_diag.detail
        return False, new_diag.detail

    except Exception as e:
        logger.warning("attempt_registration_recovery exception: %s", e)
        return False, f"Recovery attempt failed: {e}"
