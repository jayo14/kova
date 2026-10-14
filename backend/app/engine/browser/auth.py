"""Authentication barrier detection and automated authentication helpers.

Provides shared routines for detecting when a target URL is behind an
auth wall (e.g. /settings redirecting to /signin), and intelligently
logging in using available test account credentials.
"""

import asyncio
import logging
import re
from urllib.parse import urlparse
from typing import Any

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


def is_auth_url(url: str | None) -> bool:
    """Return True if the URL path matches common authentication endpoints."""
    if not url:
        return False
    path = urlparse(url).path.lower()
    return any(re.search(pat, path) for pat in AUTH_URL_PATTERNS)


async def is_auth_page(page: Any, url: str | None = None) -> bool:
    """Return True if the page URL or DOM indicates an authentication barrier."""
    current_url = url or getattr(page, "url", "")
    if is_auth_url(current_url):
        return True

    # Check for visible password input
    try:
        pwd_count = await page.locator('input[type="password"]').count()
        if pwd_count > 0:
            first_pwd = page.locator('input[type="password"]').first
            if await first_pwd.is_visible(timeout=500):
                return True
    except Exception:
        pass

    return False


def is_auth_barrier(expected_url: str | None, current_url: str | None) -> bool:
    """Detect whether a navigation was redirected to an auth wall.

    True when the expected destination was NOT an auth page, but the actual
    resulting URL is an auth page.
    """
    if not current_url:
        return False
    expected_is_auth = is_auth_url(expected_url)
    current_is_auth = is_auth_url(current_url)
    return current_is_auth and not expected_is_auth


async def find_submit_button(page: Any, password_input: Any = None) -> Any:
    """Locate the authentic form submit button, avoiding OAuth/SSO buttons."""
    oauth_keywords = ["google", "github", "apple", "microsoft", "facebook", "twitter", "sso", "saml", "okta"]
    submit_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Sign In")',
        'button:has-text("Log in")',
        'button:has-text("Log In")',
        'button:has-text("Continue")',
        'button:has-text("Submit")',
    ]

    for sel in submit_selectors:
        try:
            buttons = await page.locator(sel).all()
            for btn in buttons:
                try:
                    if not await btn.is_visible(timeout=500):
                        continue
                    txt = (await btn.inner_text(timeout=500) or "").lower()
                    if any(oa in txt for oa in oauth_keywords):
                        continue
                    return btn
                except Exception:
                    continue
        except Exception:
            continue
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


async def open_auth_view_if_needed(page: Any, is_signup: bool = False, provider: Any = None) -> bool:
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
    return await find_auth_entrance_semantically(page, provider=provider, is_signup=is_signup)


async def find_auth_inputs_semantically(
    page: Any,
    provider: Any = None,
    is_signup: bool = False,
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
) -> tuple[bool, str]:
    """Fill login or registration form, submit credentials, and wait for session.

    Handles React/SPA controlled inputs by dispatching synthetic change events,
    auto-checks terms checkboxes, and handles form submission.
    """
    if not email or not password:
        return False, "Missing email or password credentials."

    initial_url = getattr(page, "url", "")

    # Locate inputs across page and any frames
    name_input, email_input, password_input, active_scope = await find_auth_inputs_across_frames(page)

    # If inputs are not found on current page, attempt to open auth modal or navigate to auth route
    if not email_input or not password_input:
        opened = await open_auth_view_if_needed(page, is_signup=is_signup, provider=provider)
        if opened:
            name_input, email_input, password_input, active_scope = await find_auth_inputs_across_frames(page)

    # Semantic AI fallback if heuristic selectors failed to locate input fields
    if not email_input or not password_input:
        s_name, s_email, s_pwd, s_scope = await find_auth_inputs_semantically(
            page, provider=provider, is_signup=is_signup
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
        submit_btn = await find_submit_button(page, password_input)
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

        # Wait for navigation or state change
        for _ in range(12):  # up to 6 seconds
            await asyncio.sleep(0.5)
            curr = getattr(page, "url", "")
            if curr != initial_url and not is_auth_url(curr):
                return True, f"Authentication succeeded, redirected to {curr}"

        # Check if auth error message is visible
        error_locators = [
            '[role="alert"]',
            '.error-message',
            '.alert-error',
            'p:has-text("Invalid credentials")',
            'p:has-text("incorrect password")',
            'p:has-text("User not found")',
        ]
        for el_sel in error_locators:
            try:
                err_el = page.locator(el_sel).first
                if await err_el.is_visible(timeout=300):
                    err_txt = await err_el.inner_text(timeout=300)
                    return False, f"Login rejected by application: {err_txt.strip()}"
            except Exception:
                pass

        # If URL hasn't changed, check if password input has disappeared (SPA state change)
        try:
            if await page.locator('input[type="password"]').count() == 0:
                return True, "Authentication succeeded (login form dismissed)."
        except Exception:
            pass

        return False, f"Submitted credentials but page remained on auth URL: {initial_url}"

    except Exception as e:
        logger.warning("perform_login failed with exception: %s", e)
        return False, f"Error during login: {str(e)[:150]}"
