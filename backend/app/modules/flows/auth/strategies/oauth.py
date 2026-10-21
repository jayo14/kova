import json
import logging
import time
from typing import Any

from app.engine.browser.session import BrowserSession
from app.modules.flows.auth.strategies.base import AuthAttempt, AuthResult
from app.modules.flows.auth.verifier import AuthReasonCode, verify_authenticated
from app.modules.product_graph.schemas import AuthCapability

logger = logging.getLogger(__name__)


class OAuthStrategy:
    """Authenticates via pre-authenticated storage_state per persona or signals SSO_ONLY (§Prompt B)."""

    async def execute(
        self,
        capability: AuthCapability,
        browser: BrowserSession,
        credential: Any,
        execution_id: str | None = None,
        event_recorder: Any | None = None,
    ) -> AuthResult:
        login_url = capability.login_url or "/login"
        t0 = time.monotonic()
        step_id = f"auth:{capability.name}:attempt_1"

        evidence: list[dict[str, Any]] = [
            {
                "type": "event_log",
                "title": "OAuth / SSO authentication attempt",
                "purpose": "auth_attempt",
                "step_id": step_id,
                "metadata": {"url": login_url, "strategy": "oauth"},
            }
        ]

        # 1. Check for uploaded pre-authenticated storage_state per persona
        storage_state = getattr(credential, "storage_state", None)
        storage_path = getattr(credential, "storage_state_path", None)

        if not storage_state and storage_path:
            try:
                with open(storage_path, "r", encoding="utf-8") as f:
                    storage_state = json.load(f)
            except Exception as read_err:
                logger.warning("Failed to load storage_state from path %s: %s", storage_path, read_err)

        if storage_state:
            try:
                # Apply cookies to the browser context
                cookies = storage_state.get("cookies", [])
                if cookies and browser.context:
                    await browser.context.add_cookies(cookies)

                # Navigate to the target page
                dest_url = capability.login_url or "/dashboard"
                await browser.navigate(dest_url)

                # Run verify_authenticated
                is_authed, reason_code = await verify_authenticated(browser, capability)

                if is_authed:
                    session_state = await browser.save_session_state()
                    return AuthResult(
                        success=True,
                        session_state=session_state,
                        reason_code=AuthReasonCode.SUCCESS,
                        evidence=evidence,
                        attempts=[AuthAttempt(attempt_number=1, strategy="oauth", success=True, reason_code=AuthReasonCode.SUCCESS, duration_ms=int((time.monotonic() - t0) * 1000))],
                    )
                else:
                    return AuthResult(
                        success=False,
                        failure_reason=f"Uploaded storage_state was applied but session verification failed: {reason_code}",
                        reason_code=reason_code,
                        failure_category="AUTH",
                        evidence=evidence,
                        attempts=[AuthAttempt(attempt_number=1, strategy="oauth", success=False, error=reason_code, reason_code=reason_code, duration_ms=int((time.monotonic() - t0) * 1000))],
                    )
            except Exception as e:
                logger.error("Failed to restore storage_state for OAuth strategy: %s", e)
                return AuthResult(
                    success=False,
                    failure_reason=f"Error restoring storage_state: {e}",
                    reason_code=AuthReasonCode.UNKNOWN,
                    failure_category="AUTH",
                    evidence=evidence,
                    attempts=[AuthAttempt(attempt_number=1, strategy="oauth", success=False, error=str(e), duration_ms=int((time.monotonic() - t0) * 1000))],
                )

        # 2. When no pre-authenticated storage_state exists, return SSO_ONLY with clear instructions
        error_msg = (
            "SSO_ONLY: Third-party OAuth / SSO authentication requires an uploaded pre-authenticated "
            "storage_state (cookies/session state JSON) for persona '%s'. "
            "Please export your authenticated browser session and upload it to the persona credentials."
            % getattr(capability, "persona", "default")
        )

        if event_recorder:
            try:
                event_recorder(
                    "agent_question",
                    {
                        "type": "oauth_storage_state_required",
                        "question": error_msg,
                        "persona": getattr(capability, "persona", "default"),
                    },
                )
            except Exception:
                pass

        return AuthResult(
            success=False,
            failure_reason=error_msg,
            reason_code=AuthReasonCode.SSO_ONLY,
            failure_category="AUTH",
            evidence=evidence,
            attempts=[AuthAttempt(attempt_number=1, strategy="oauth", success=False, error="SSO_ONLY: Missing pre-authenticated storage_state", reason_code=AuthReasonCode.SSO_ONLY, duration_ms=int((time.monotonic() - t0) * 1000))],
        )
