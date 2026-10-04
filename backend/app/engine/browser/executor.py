"""Action executor for browser automation.

Orchestrates the action lifecycle: validate → resolve → emit → execute → emit.
"""

import asyncio
import logging
import uuid
from typing import Any

from playwright.async_api import Page

from app.engine.browser.actions import (
    Action,
    ActionExecutionError,
    ActionType,
    ActionValidationError,
    mask_sensitive,
    sanitize_for_log,
    validate_action,
)
from app.engine.browser.resolver import (
    AmbiguousTargetError,
    ResolutionStrategy,
    TargetNotFoundError,
    TargetResolver,
)
from app.engine.credentials.store import CredentialStore

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes structured browser actions.

    Lifecycle for each action:
        1. Validate action schema
        2. Resolve credential references (if any)
        3. Resolve target to locator
        4. Emit action.started event
        5. Execute browser action
        6. Emit action.completed event
        7. Return result

    On failure: returns structured ActionExecutionError.

    Credentials are NEVER logged, included in event payloads, or exposed in errors.
    """

    def __init__(
        self,
        page: Page,
        event_recorder: Any | None = None,
        credential_store: CredentialStore | None = None,
    ):
        """Initialize the executor.

        Args:
            page: Playwright page to execute actions on.
            event_recorder: Optional callable(event_type, payload) for events.
                If None, events are skipped (useful for testing).
            credential_store: Optional store for credential resolution.
                If None, credential references will fail with a clear error.
        """
        self.page = page
        self.resolver = TargetResolver(page)
        self._event_recorder = event_recorder
        self._credential_store = credential_store or CredentialStore()

    async def execute(
        self,
        raw_action: dict,
        execution_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute a raw action dict.

        Args:
            raw_action: Raw action dictionary from flow steps.
                May contain 'credential_id' to reference stored credentials.
                The credential_id is resolved to actual values before execution.
            execution_id: Optional execution ID for event recording.

        Returns:
            {"success": True, "action": {...}, "result": {...}}
            or {"success": False, "error": {...}}
        """
        # Step 1: Validate
        try:
            action = validate_action(raw_action)
        except ActionValidationError as e:
            logger.warning("Action validation failed: %s", e)
            return {
                "success": False,
                "error": {
                    "type": "validation_error",
                    "message": str(e),
                    "action_type": e.action_type,
                    "errors": e.errors,
                },
            }

        # Step 2: Resolve credential reference (if present)
        credential_id = raw_action.get("credential_id")
        if credential_id:
            credential_field = raw_action.get("credential_field", "password")
            try:
                resolved_value = await self._resolve_credential(
                    credential_id, action, field=credential_field
                )
                if resolved_value is not None:
                    action.value = resolved_value
            except ActionExecutionError as e:
                logger.warning("Credential resolution failed: %s", e.message)
                return {
                    "success": False,
                    "error": {
                        "type": "credential_error",
                        "message": e.message,
                        "action_type": e.action_type,
                        "error_code": e.error_code,
                    },
                }

        action_dict = sanitize_for_log(action.to_dict())
        logger.debug("Executing action: %s", action_dict)

        # Step 3: Emit action.started (never include value/password in payload)
        emit_payload: dict[str, Any] = {
            "action": action.type.value,
            "target": action.target.to_dict(),
        }
        if credential_id:
            emit_payload["credential_id"] = credential_id
        await self._emit(execution_id, "action.started", emit_payload)

        # Step 4: Resolve target (if needed)
        locator = None
        actions_needing_target = {
            ActionType.CLICK,
            ActionType.TYPE,
            ActionType.CLEAR,
            ActionType.SELECT,
            ActionType.CHECK,
            ActionType.UNCHECK,
            ActionType.UPLOAD,
        }
        if action.type in actions_needing_target:
            try:
                locator = await self._resolve_target(action)
            except TargetNotFoundError as e:
                logger.warning("Target not found: %s", e)
                await self._emit(
                    execution_id,
                    "action.failed",
                    {
                        "action": action.type.value,
                        "error": "target_not_found",
                        "message": str(e),
                    },
                )
                return {
                    "success": False,
                    "error": {
                        "type": "target_not_found",
                        "message": str(e),
                        "action_type": action.type.value,
                        "target": action.target.to_dict(),
                    },
                }

        # Step 5: Execute
        try:
            result = await self._execute_action(action, locator)
        except Exception as e:
            # Never include action.value (password) in error messages
            safe_error = _safe_error_message(e)
            logger.warning("Action execution failed: %s", safe_error)
            await self._emit(
                execution_id,
                "action.failed",
                {
                    "action": action.type.value,
                    "error": "execution_error",
                    "message": safe_error,
                },
            )
            return {
                "success": False,
                "error": {
                    "type": "execution_error",
                    "message": safe_error,
                    "action_type": action.type.value,
                    "target": action.target.to_dict(),
                },
            }

        # Step 6: Emit action.completed
        await self._emit(
            execution_id,
            "action.completed",
            {"action": action.type.value, "target": action.target.to_dict()},
        )

        logger.debug("Action completed: %s", action_dict)
        return {
            "success": True,
            "action": action_dict,
            "result": result,
        }

    async def _resolve_credential(
        self, credential_id: str, action: Action, field: str = "password"
    ) -> str | None:
        """Resolve a credential reference to a value.

        For 'type' actions with credential_id, returns the credential's password
        or email depending on `field`. The secret is NEVER logged or included in
        payloads.
        """
        try:
            credential = self._credential_store.get(credential_id)
            if field == "email":
                return credential.email
            raw_password = credential.get_password()
            from app.modules.credentials.crypto import decrypt_credential
            return decrypt_credential(raw_password)
        except Exception:
            # Never expose credential details in error
            logger.warning("Credential resolution failed for %s", credential_id)
            raise ActionExecutionError(
                action_type=action.type.value,
                message=f"Credential not found: {credential_id}",
                error_code="credential_not_found",
            ) from None

    async def _resolve_target(self, action: Action):
        """Resolve action target to a Playwright Locator."""
        target = action.target

        try:
            # Map ActionTarget fields to resolver
            if target.test_id:
                return await self.resolver.resolve(
                    target.test_id, strategy=ResolutionStrategy.TEST_ID
                )
            if target.role and target.name:
                return await self.resolver.resolve(
                    target.name, role=target.role, strategy=ResolutionStrategy.ROLE_NAME
                )
            if target.label:
                return await self.resolver.resolve(
                    target.label, strategy=ResolutionStrategy.LABEL
                )
            if target.text:
                return await self.resolver.resolve(
                    target.text, strategy=ResolutionStrategy.TEXT
                )
            if target.css:
                return await self.resolver.resolve(
                    target.css, strategy=ResolutionStrategy.CSS
                )
            if target.name:
                # Try name as generic target
                return await self.resolver.resolve(target.name)
        except AmbiguousTargetError as amb_err:
            logger.info(
                "Ambiguous target '%s' (%d matches); resolving to first visible element",
                amb_err.target,
                amb_err.count,
            )
            try:
                if target.test_id:
                    return await self.resolver.resolve_first_visible(
                        target.test_id, strategy=ResolutionStrategy.TEST_ID
                    )
                if target.role and target.name:
                    return await self.resolver.resolve_first_visible(
                        target.name, role=target.role, strategy=ResolutionStrategy.ROLE_NAME
                    )
                if target.label:
                    return await self.resolver.resolve_first_visible(
                        target.label, strategy=ResolutionStrategy.LABEL
                    )
                if target.text:
                    return await self.resolver.resolve_first_visible(
                        target.text, strategy=ResolutionStrategy.TEXT
                    )
                if target.css:
                    return await self.resolver.resolve_first_visible(
                        target.css, strategy=ResolutionStrategy.CSS
                    )
                if target.name:
                    return await self.resolver.resolve_first_visible(target.name)
            except Exception:
                pass

        raise TargetNotFoundError(str(target.to_dict()))

    async def _execute_action(self, action: Action, locator=None) -> dict[str, Any]:
        """Execute the browser action."""
        if action.type == ActionType.NAVIGATE:
            from app.engine.browser.session import _is_safe_url
            if not _is_safe_url(action.value or ""):
                raise ActionValidationError(
                    "navigate",
                    [f"Blocked navigation to unsafe URL: {action.value}"],
                )
            await self.page.goto(action.value, wait_until="domcontentloaded", timeout=45000)
            final_url = self.page.url or ""
            if final_url and not _is_safe_url(final_url):
                raise ActionValidationError(
                    "navigate",
                    [f"Blocked post-redirect navigation to unsafe URL: {final_url}"],
                )
            return {"url": final_url, "title": await self.page.title()}

        elif action.type == ActionType.CLICK:
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            # Click and wait for navigation if one occurs
            navigation_occurred = False
            try:
                async with self.page.expect_navigation(
                    wait_until="domcontentloaded",
                    timeout=5000,
                ):
                    try:
                        await locator.click(timeout=3000)
                    except Exception:
                        try:
                            await locator.click(force=True, timeout=2000)
                        except Exception:
                            await locator.dispatch_event("click")
                navigation_occurred = True
            except Exception:
                # No navigation occurred within 5s — that's fine, click still happened
                pass

            # Brief wait for any dynamic content to settle after navigation
            if navigation_occurred:
                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

            return {"clicked": True, "navigation": navigation_occurred}

        elif action.type == ActionType.TYPE:
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            try:
                await locator.focus()
            except Exception:
                pass
            await locator.fill(action.value or "")
            try:
                await locator.evaluate(
                    "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                )
            except Exception:
                pass
            return {"typed": True}

        elif action.type == ActionType.CLEAR:
            try:
                await locator.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            await locator.fill("")
            try:
                await locator.evaluate(
                    "el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }"
                )
            except Exception:
                pass
            return {"cleared": True}

        elif action.type == ActionType.SELECT:
            await locator.select_option(action.value)
            return {"selected": action.value}

        elif action.type == ActionType.CHECK:
            await locator.check()
            return {"checked": True}

        elif action.type == ActionType.UNCHECK:
            await locator.uncheck()
            return {"unchecked": True}

        elif action.type == ActionType.UPLOAD:
            await locator.set_input_files(action.value)
            return {"uploaded": True}

        elif action.type == ActionType.WAIT:
            duration = 1.0
            if action.value:
                try:
                    val = float(action.value)
                    duration = val / 1000.0 if val >= 50.0 else val
                except ValueError:
                    duration = 1.0
            elif action.amount:
                duration = action.amount / 1000.0
            await asyncio.sleep(min(duration, 30.0))
            return {"waited_s": duration}

        elif action.type == ActionType.PRESS:
            await self.page.keyboard.press(action.key)
            return {"pressed": action.key}

        elif action.type == ActionType.SCROLL:
            direction = action.direction or "down"
            amount = action.amount or 500
            delta = amount if direction == "down" else -amount
            await self.page.mouse.wheel(0, delta)
            return {"scrolled": direction, "amount": amount}

        elif action.type == ActionType.BACK:
            await self.page.go_back(wait_until="domcontentloaded")
            return {"url": self.page.url, "title": await self.page.title()}

        elif action.type == ActionType.FORWARD:
            await self.page.go_forward(wait_until="domcontentloaded")
            return {"url": self.page.url, "title": await self.page.title()}

        elif action.type == ActionType.RELOAD:
            await self.page.reload(wait_until="domcontentloaded")
            return {"url": self.page.url, "title": await self.page.title()}

        return {}

    async def _emit(
        self,
        execution_id: uuid.UUID | None,
        event_type: str,
        payload: dict,
    ):
        """Emit an event if recorder is configured."""
        if self._event_recorder and execution_id:
            try:
                await self._event_recorder(execution_id, event_type, payload)
            except Exception as e:
                logger.warning("Failed to emit event %s: %s", event_type, e)


def _safe_error_message(exc: Exception) -> str:
    """Create an error message that never includes sensitive values.

    Replaces any potential password/secret values with masks.
    """
    msg = str(exc)
    # If message contains common password patterns, mask them
    if any(s in msg.lower() for s in ["password", "secret", "credential"]):
        return "An error occurred during action execution"
    return msg
