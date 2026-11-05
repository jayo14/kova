"""Intelligent Authentication Strategy Evaluator.

Application-agnostic evaluation of authentication surfaces:
1. Discovers all exposed authentication doors:
   - External OAuth (Google, GitHub, Apple, Microsoft, etc.)
   - Native credentials login (email/username + password)
   - Native self-registration (account creation forms or links)
   - Magic link / passwordless
   - Password recovery
2. Evaluates the viability of competing access strategies:
   - Configured project credentials evaluate native sign in.
   - Unauthenticated sandboxes evaluate native self-registration.
   - External OAuth requires pre-existing third-party accounts and external redirects;
     prioritized after first-party options and marked unviable if failing to navigate.
3. Emits structured activity events exposing the decision-making process.
4. Prevents repetitive and unproductive authentication attempts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction
from app.engine.exploration.agent.understanding import ApplicationUnderstanding

logger = logging.getLogger(__name__)

OAUTH_PROVIDERS = [
    "google", "github", "apple", "microsoft", "facebook", "twitter", "x", "okta", "auth0"
]


@dataclass
class AuthOption:
    method_type: str                  # "native_login", "self_registration", "oauth", "magic_link", "recovery"
    provider: str | None = None       # "google", "github", None
    label: str = ""
    selector: str | None = None
    target_url: str | None = None
    is_external: bool = False
    is_first_party: bool = True
    element: dict[str, Any] | None = None


@dataclass
class AuthSurfaceAnalysis:
    is_auth_surface: bool = False
    options: list[AuthOption] = field(default_factory=list)
    has_native_login: bool = False
    has_registration_form: bool = False
    has_registration_link: bool = False
    has_oauth: bool = False
    is_on_login_path: bool = False
    is_on_register_path: bool = False

    def options_summary(self) -> str:
        parts = []
        for opt in self.options:
            if opt.provider:
                parts.append(f"{opt.provider.capitalize()} OAuth")
            elif opt.method_type == "native_login":
                parts.append("email/password sign-in")
            elif opt.method_type == "self_registration":
                parts.append("account registration")
            elif opt.method_type == "magic_link":
                parts.append("magic link / OTP")
            elif opt.method_type == "recovery":
                parts.append("password recovery")
        return ", ".join(parts) if parts else "none"


class AuthStrategyEvaluator:
    """Evaluates available doors into an application and selects the most viable path."""

    @staticmethod
    def analyze_surface(observation: dict[str, Any], current_url: str) -> AuthSurfaceAnalysis:
        analysis = AuthSurfaceAnalysis()
        path = urlparse(current_url).path.lower()
        analysis.is_on_login_path = any(p in path for p in ("/login", "/signin", "/sign-in", "/log-in", "/auth/login"))
        analysis.is_on_register_path = any(p in path for p in ("/register", "/signup", "/sign-up", "/join", "/registration", "/auth/signup"))

        elements = observation.get("elements", []) or observation.get("interactive_elements", []) or []
        links = observation.get("links", []) or []
        controls = observation.get("controls", []) or []

        # 1. Detect password and email inputs
        has_password = False
        has_email = False
        has_name_input = False

        for el in elements:
            el_type = str(el.get("type") or el.get("input_type") or "").lower()
            name_str = " ".join([
                str(el.get("name") or ""),
                str(el.get("label") or ""),
                str(el.get("placeholder") or ""),
                str(el.get("id") or ""),
                str(el.get("autocomplete") or ""),
            ]).lower()

            if el_type == "password" or "password" in name_str:
                has_password = True
            elif el_type == "email" or any(k in name_str for k in ("email", "username", "login")):
                has_email = True
            elif any(k in name_str for k in ("full name", "fullname", "name", "logbook")):
                has_name_input = True

        # Check forms
        forms = observation.get("forms", []) or []
        has_submit_btn = any(
            str(c.get("type") or "").lower() == "submit" or
            any(k in str(c.get("name") or c.get("text") or "").lower() for k in ("sign in", "login", "create account", "register"))
            for c in controls
        )

        # 2. Native login form
        if has_password and has_email and (analysis.is_on_login_path or not analysis.is_on_register_path):
            analysis.has_native_login = True
            submit_control = next(
                (c for c in controls if any(k in str(c.get("name") or c.get("text") or "").lower() for k in ("sign in", "log in", "login"))),
                None
            )
            analysis.options.append(AuthOption(
                method_type="native_login",
                label="Email & Password Sign-in",
                selector=submit_control.get("selector") if submit_control else "button[type='submit']",
                is_first_party=True,
                is_external=False,
                element=submit_control,
            ))

        # 3. Native self-registration (form or link)
        if analysis.is_on_register_path and (has_password or has_submit_btn):
            analysis.has_registration_form = True
            submit_control = next(
                (c for c in controls if any(k in str(c.get("name") or c.get("text") or "").lower() for k in ("create account", "sign up", "register", "submit"))),
                None
            )
            analysis.options.append(AuthOption(
                method_type="self_registration",
                label="Native Account Registration Form",
                selector=submit_control.get("selector") if submit_control else "button[type='submit']",
                is_first_party=True,
                is_external=False,
                element=submit_control,
            ))
        else:
            # Check for link to registration
            all_interactives = links + controls + elements
            reg_link = next(
                (
                    el for el in all_interactives
                    if (
                        any(k in str(el.get("name") or el.get("text") or el.get("label") or "").lower() for k in ("create an account", "create account", "register", "sign up", "sign-up", "join", "get started"))
                        or any(k in str(el.get("href") or el.get("url") or "").lower() for k in ("/register", "/signup", "/sign-up", "/join", "/auth/signup"))
                    )
                    and not any(k in str(el.get("name") or el.get("text") or "").lower() for k in ("google", "apple", "github", "microsoft"))
                ),
                None
            )
            if reg_link:
                analysis.has_registration_link = True
                href = reg_link.get("href") or reg_link.get("url") or "/register"
                if href.startswith("/") and current_url:
                    href = urljoin(current_url, href)
                analysis.options.append(AuthOption(
                    method_type="self_registration",
                    label="Account Registration Link",
                    selector=reg_link.get("selector") or f"a:has-text('{reg_link.get('name') or 'Create an account'}')",
                    target_url=href,
                    is_first_party=True,
                    is_external=False,
                    element=reg_link,
                ))

        # Check for link to sign in (especially when on registration page)
        login_link = next(
            (
                el for el in (links + controls + elements)
                if (
                    any(k in str(el.get("name") or el.get("text") or el.get("label") or "").lower() for k in ("sign in", "log in", "login", "already have an account"))
                    or any(k in str(el.get("href") or el.get("url") or "").lower() for k in ("/login", "/signin", "/sign-in", "/log-in"))
                )
                and not any(k in str(el.get("name") or el.get("text") or "").lower() for k in ("google", "apple", "github", "microsoft"))
            ),
            None
        )
        if login_link and (analysis.is_on_register_path or not analysis.has_native_login):
            href = login_link.get("href") or login_link.get("url") or "/login"
            if href.startswith("/") and current_url:
                href = urljoin(current_url, href)
            analysis.options.append(AuthOption(
                method_type="native_login",
                label="Sign-in Link",
                selector=login_link.get("selector") or f"a:has-text('{login_link.get('name') or 'Sign in'}')",
                target_url=href,
                is_first_party=True,
                is_external=False,
                element=login_link,
            ))

        # 4. External OAuth providers
        all_buttons = controls + [e for e in elements if e.get("type") in ("button", "link")]
        seen_providers: set[str] = set()

        for btn in all_buttons:
            text = " ".join([
                str(btn.get("name") or ""),
                str(btn.get("text") or ""),
                str(btn.get("label") or ""),
                str(btn.get("aria-label") or ""),
                str(btn.get("selector") or ""),
            ]).lower()

            for provider in OAUTH_PROVIDERS:
                if provider in text and provider not in seen_providers:
                    # e.g. "continue with google", "sign in with google", "sign up with google"
                    if any(k in text for k in ("continue with", "sign in with", "sign up with", "login with", "google", "oauth", "sso")):
                        seen_providers.add(provider)
                        analysis.has_oauth = True
                        analysis.options.append(AuthOption(
                            method_type="oauth",
                            provider=provider,
                            label=f"{provider.capitalize()} OAuth",
                            selector=btn.get("selector") or f"button:has-text('{provider.capitalize()}')",
                            is_first_party=False,
                            is_external=True,
                            element=btn,
                        ))

        # 5. Password recovery
        for link in links:
            txt = str(link.get("name") or link.get("text") or "").lower()
            if "forgot" in txt and "password" in txt:
                analysis.options.append(AuthOption(
                    method_type="recovery",
                    label="Forgot Password Link",
                    selector=link.get("selector") or "a:has-text('Forgot password?')",
                    target_url=link.get("href"),
                    is_first_party=True,
                    is_external=False,
                    element=link,
                ))
                break

        analysis.is_auth_surface = (
            analysis.is_on_login_path
            or analysis.is_on_register_path
            or has_password
            or len(analysis.options) > 0
        )
        return analysis

    @staticmethod
    def select_strategy(
        analysis: AuthSurfaceAnalysis,
        credentials: dict[str, Any] | None,
        understanding: ApplicationUnderstanding,
    ) -> tuple[AuthOption | None, str]:
        """Selects the justified authentication strategy based on available options and sandbox constraints.

        Enforces single-identity lifecycle:
        - If registration was already submitted for this mission, never re-register or cycle to OAuth.
        - If an exploration identity exists, attempt login with those credentials instead.
        - External OAuth is never selected as a silent fallback; it requires human-interactive
          delegation and is blocked unless explicitly configured.
        """
        if not analysis.options:
            return None, "No viable authentication options discovered."

        attempted_keys = {
            f"{att.get('type')}:{att.get('provider') or 'native'}"
            for att in understanding.attempted_auth_strategies
            if not att.get("success")
        }

        # Single-identity guard: if registration was already submitted, do NOT register again
        # or cycle to OAuth. Instead, attempt login with the existing exploration identity.
        if understanding.should_attempt_login_instead():
            # Find a login option (form on current page or link to login)
            native_login_opt = next((o for o in analysis.options if o.method_type == "native_login"), None)
            if native_login_opt and "native_login:native:retry" not in attempted_keys:
                return (
                    native_login_opt,
                    "Registration already submitted for this identity; attempting login with existing exploration credentials.",
                )
            # If we're on the register page but have a login link, navigate to login
            if analysis.is_on_register_path:
                login_link = next((o for o in analysis.options if o.method_type == "native_login" and o.target_url), None)
                if login_link:
                    return (
                        login_link,
                        "Registration already submitted; navigating to sign-in to authenticate with existing exploration credentials.",
                    )
            return None, "Registration already submitted for this identity; waiting for session settlement or login surface."

        # 1. Configured Project Credentials -> Native Sign-in
        if credentials and credentials.get("email") and credentials.get("password"):
            native_login_opt = next((o for o in analysis.options if o.method_type == "native_login"), None)
            if native_login_opt and "native_login:native" not in attempted_keys:
                return (
                    native_login_opt,
                    "Configured project credentials available; attempting direct first-party sign in.",
                )

        # 2. If on Registration form -> Complete native registration (first time only)
        if analysis.is_on_register_path or analysis.has_registration_form:
            if not understanding.registration_submitted:
                reg_form_opt = next((o for o in analysis.options if o.method_type == "self_registration"), None)
                if reg_form_opt and "self_registration:native" not in attempted_keys:
                    return (
                        reg_form_opt,
                        "On native registration form; proceeding to create an authorized exploration account.",
                    )

        # 3. If on Login view with Registration link -> Navigate to self-registration (first time only)
        if analysis.has_registration_link:
            if not understanding.registration_submitted:
                reg_link_opt = next((o for o in analysis.options if o.method_type == "self_registration"), None)
                if reg_link_opt and "self_registration:native" not in attempted_keys:
                    return (
                        reg_link_opt,
                        "No existing credentials provided; native self-registration discovered and selected as primary access path.",
                    )

        # 4. If credentials exist but we are on registration page -> Navigate to sign in
        if credentials and analysis.is_on_register_path:
            login_link_opt = next((o for o in analysis.options if o.method_type == "native_login"), None)
            if login_link_opt:
                return (
                    login_link_opt,
                    "Project credentials available; transitioning to sign-in view.",
                )

        # 5. External OAuth: BLOCKED for automated exploration
        # OAuth requires human-interactive delegation with pre-existing third-party accounts.
        # In an isolated sandbox without configured OAuth tokens, clicking OAuth buttons
        # redirects to external providers that cannot be completed autonomously.
        # This is NOT a viable fallback when native registration did not immediately redirect.
        oauth_opts = [
            o for o in analysis.options
            if o.method_type == "oauth" and f"oauth:{o.provider}" not in attempted_keys
        ]
        if oauth_opts:
            # Mark OAuth as blocked, not as a strategy to attempt
            for oauth_opt in oauth_opts:
                understanding.record_auth_method(
                    method_type="oauth",
                    provider=oauth_opt.provider,
                    label=oauth_opt.label,
                    viable=False,
                )
            return None, "External OAuth requires human-interactive delegation; blocked in automated exploration sandbox."

        return None, "All discovered authentication options have been attempted without granting access."

    @staticmethod
    def propose_action_for_strategy(
        strategy: AuthOption,
        credentials: dict[str, Any] | None,
        node_id: str,
        understanding: Any = None,
    ) -> AgentActionProposal | None:
        """Converts the selected authentication strategy into a targeted epistemic action."""
        if strategy.method_type == "self_registration":
            if strategy.target_url:
                target = dict(strategy.element or {})
                target["url"] = strategy.target_url
                target["href"] = strategy.target_url
                target["text"] = (strategy.element or {}).get("name") or (strategy.element or {}).get("text") or strategy.label
                target["selector"] = (strategy.element or {}).get("selector") or strategy.selector
                return AgentActionProposal(
                    action=ExplorationAction.OPEN_LINK,
                    target=target,
                    reason="navigate to native self-registration to acquire workspace access",
                    confidence=0.85,
                )
            else:
                # Currently on registration form: execute registration
                import uuid
                existing = getattr(understanding, "exploration_identity", None) if understanding is not None else None
                if existing and existing.get("email") and existing.get("password"):
                    creds = {
                        "name": existing.get("name") or "Kova Tester",
                        "email": existing["email"],
                        "password": existing["password"],
                    }
                else:
                    synthetic_email = f"test.kova.{uuid.uuid4().hex[:6]}@gmail.com"
                    synthetic_pwd = f"SecurePassword123!{uuid.uuid4().hex[:4]}"
                    creds = {
                        "name": "Kova Tester",
                        "email": synthetic_email,
                        "password": synthetic_pwd,
                    }
                    if understanding is not None and hasattr(understanding, "set_exploration_identity"):
                        understanding.set_exploration_identity(creds["email"], creds["password"], creds["name"])
                return AgentActionProposal(
                    action=ExplorationAction.AUTHENTICATE,
                    target={"credentials": creds, "is_signup": True, "selector": strategy.selector},
                    reason="execute native self-registration to establish application session",
                    confidence=0.9,
                )

        elif strategy.method_type == "native_login":
            if strategy.target_url:
                target = dict(strategy.element or {})
                target["url"] = strategy.target_url
                target["href"] = strategy.target_url
                target["text"] = (strategy.element or {}).get("name") or (strategy.element or {}).get("text") or strategy.label
                target["selector"] = (strategy.element or {}).get("selector") or strategy.selector
                return AgentActionProposal(
                    action=ExplorationAction.OPEN_LINK,
                    target=target,
                    reason="navigate to sign-in form to authenticate",
                    confidence=0.85,
                )
            else:
                return AgentActionProposal(
                    action=ExplorationAction.AUTHENTICATE,
                    target={"credentials": credentials or {}, "is_signup": False, "selector": strategy.selector},
                    reason="authenticate with configured project credentials",
                    confidence=0.9,
                )

        elif strategy.method_type == "oauth":
            target = dict(strategy.element or {})
            target["provider"] = strategy.provider
            target["text"] = (strategy.element or {}).get("name") or (strategy.element or {}).get("text") or strategy.label
            target["selector"] = (strategy.element or {}).get("selector") or strategy.selector
            return AgentActionProposal(
                action=ExplorationAction.CLICK_CONTROL,
                target=target,
                reason=f"investigate {strategy.provider.capitalize()} OAuth external authentication provider",
                confidence=0.4,
            )

        return None
