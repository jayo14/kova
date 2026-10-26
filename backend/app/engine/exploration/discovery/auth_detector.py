from __future__ import annotations

import logging
from typing import Any

from app.engine.browser.auth import classify_auth_page, observe_auth_signals
from app.modules.flows.schemas import StateAssertion, StateMutation
from app.modules.product_graph.schemas import Action, AuthCapability, Page, Persona

logger = logging.getLogger(__name__)


class AuthDetector:
    def __init__(self):
        pass

    async def inspect_page_auth(self, browser_page: Any, page: Page) -> None:
        """Inspect a loaded page for authentication signals and update page.requires_auth and required_state."""
        try:
            bundle = await observe_auth_signals(browser_page, page.url_pattern)
            classification = classify_auth_page(bundle)

            if classification.kind in ("login", "signup", "magic_link", "otp_verification", "oauth_redirect"):
                page.requires_auth = True
                page.required_state = [StateAssertion(key="authenticated", value=False, predicate="eq")]
                page.confidence = classification.confidence
                page.source = "discovered" if classification.confidence >= 0.7 else "heuristic"
            elif bundle.visible_password_input_count > 0 or bundle.visible_email_input_count > 0:
                page.requires_auth = True
                page.required_state = [StateAssertion(key="authenticated", value=False, predicate="eq")]
                page.confidence = 0.85
                page.source = "discovered"
            # URL paths such as /dashboard, /admin or /account are NOT
            # evidence that a page requires authentication: public pages,
            # marketing routes and 404s can share those paths. Leave
            # requires_auth unchanged rather than guess from the URL alone.
        except Exception as e:
            logger.warning("Auth inspection failed for %s: %s", page.url_pattern, e)

    async def detect_auth(
        self, pages: list[Page], actions: list[Action], personas: list[Persona]
    ) -> list[AuthCapability]:
        """Detect auth pages and produce AuthCapability rows for the Product Graph."""
        auth_capabilities: list[AuthCapability] = []
        for page in pages:
            p_lower = page.url_pattern.lower()
            is_login_page = any(k in p_lower for k in ("/login", "/signin", "/sign-in", "/log-in", "/session", "/frame/login"))
            page_actions = [a for a in actions if a.page_id == page.id]
            has_auth_actions = any(
                any(k in (a.selector or "").lower() for k in ("password", "otp", "code", "login", "signin", "modal", "auth", "identifier", "username"))
                for a in page_actions
            )
            if not is_login_page and not has_auth_actions and not (page.requires_auth and any(k in p_lower for k in ("auth", "register", "signup"))):
                continue

            strategy = self._infer_strategy(page, actions)
            success_pattern = self._infer_success_pattern(page, personas, pages)

            persona_list = personas or [Persona(name="default", project_id=page.project_id)]
            for persona in persona_list:
                auth_cap = AuthCapability(
                    project_id=page.project_id,
                    name=f"Authenticate as {persona.name}",
                    description=f"Login via {page.url_pattern} as {persona.name}",
                    kind="auth",
                    auth_strategy=strategy,
                    login_url=page.url_pattern,
                    success_url_pattern=success_pattern,
                    success_state_assertion=StateAssertion(
                        key="authenticated", value=True, predicate="eq"
                    ),
                    produces_state=[StateMutation(key="authenticated", value=True)],
                    persona=persona.name,
                    requires_capabilities=[
                        f"login_url:{page.url_pattern}",
                        f"strategy:{strategy}",
                        f"persona:{persona.name}",
                        f"success_pattern:{success_pattern}",
                    ],
                    confidence=0.85,
                    source="discovered",
                )
                auth_capabilities.append(auth_cap)
        return auth_capabilities

    def _infer_strategy(self, page: Page, actions: list[Action]) -> str:
        page_actions = [a for a in actions if a.page_id == page.id]
        selectors = " ".join([a.selector.lower() for a in page_actions])
        if "magic" in selectors:
            return "magic_link"
        if "otp" in selectors:
            return "otp"
        return "password_form"

    def _infer_success_pattern(self, page: Page, personas: list[Persona], pages: list[Page]) -> str:
        for p in pages:
            pl = p.url_pattern.lower()
            if any(k in pl for k in ("/dashboard", "/workspace", "/home", "/app", "/overview")):
                return p.url_pattern
        return "/"

