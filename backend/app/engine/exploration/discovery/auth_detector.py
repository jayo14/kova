from __future__ import annotations

import logging
from typing import Any

from app.engine.browser.auth import classify_auth_page, observe_auth_signals
from app.modules.flows.schemas import StateAssertion
from app.modules.product_graph.schemas import Page

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
            elif bundle.visible_password_input_count > 0 or bundle.visible_email_input_count > 0 or bundle.url_path_is_auth:
                page.requires_auth = True
                page.required_state = [StateAssertion(key="authenticated", value=False, predicate="eq")]
                page.confidence = 0.85
                page.source = "discovered"
            else:
                # Check if page is protected (e.g. requires logged-in state) based on role/auth paths
                p_lower = page.url_pattern.lower()
                if any(k in p_lower for k in ("/dashboard", "/admin", "/settings", "/profile", "/account", "/portal")):
                    page.requires_auth = True
                    page.required_state = [StateAssertion(key="authenticated", value=True, predicate="eq")]
                    page.confidence = 0.8
                    page.source = "heuristic"
        except Exception as e:
            logger.warning("Auth inspection failed for %s: %s", page.url_pattern, e)
