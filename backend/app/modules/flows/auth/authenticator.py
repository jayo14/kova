import logging
from typing import Any

from app.engine.browser.session import BrowserSession
from app.modules.flows.auth.strategies import (
    AuthResult,
    MagicLinkStrategy,
    OAuthStrategy,
    OTPStrategy,
    PasswordFormStrategy,
)
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class Authenticator:
    """Executes authentication capabilities against live browser sessions."""

    def __init__(self):
        self._strategies = {
            "password_form": PasswordFormStrategy(),
            "magic_link": MagicLinkStrategy(),
            "oauth": OAuthStrategy(),
            "otp": OTPStrategy(),
        }

    async def authenticate(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        strategy_name = getattr(capability, "auth_strategy", "password_form") or "password_form"
        strategy = self._strategies.get(strategy_name)

        if not strategy:
            logger.warning("Unknown auth strategy '%s', falling back to password_form", strategy_name)
            strategy = self._strategies["password_form"]

        logger.info(
            "Executing auth capability '%s' using strategy '%s' for persona '%s'",
            capability.name,
            strategy_name,
            getattr(capability, "persona", "default"),
        )

        return await strategy.execute(
            capability=capability,
            browser=browser,
            credential=credential,
            execution_id=execution_id,
            event_recorder=event_recorder,
        )
