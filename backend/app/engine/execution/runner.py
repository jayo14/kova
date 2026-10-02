"""Deterministic execution runner.

Orchestrates the complete lifecycle of a flow execution:
load → queue → init browser → run steps → verify → complete/fail → cleanup

Never leaves execution stuck in RUNNING.
Always transitions to terminal state on exit.
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.engine.browser.actions import ActionType
from app.engine.browser.executor import ActionExecutor
from app.engine.browser.session import BrowserSession
from app.engine.browser.screenshot_storage import screenshot_storage
from app.engine.credentials.store import CredentialStore
from app.engine.execution.context import ExecutionContext
from app.engine.execution.state import ExecutionState
from app.engine.verification.verifier import Verifier
from app.modules.executions.event_types import EventTypes
from app.engine.execution.stream import publish_frame, publish_state
from app.engine.execution.control import (
    get_control_state,
    get_pending_input,
    check_pause,
    is_cancel_requested,
    cleanup_control,
)

logger = logging.getLogger(__name__)

# Maximum execution duration in seconds (PRD §22)
EXECUTION_TIMEOUT_SECONDS = 300  # 5 minutes

# Live frame cadence for the viewport stream (~4 FPS, latest-wins)
FRAME_INTERVAL_SECONDS = 0.25
# Poll interval while paused: drain input → apply → frame → check resume
PAUSE_POLL_SECONDS = 0.05
# Pause hard timeout — auto-resume so execution never sticks in PAUSED
PAUSE_TIMEOUT_SECONDS = 300.0

# Maximum number of action retries for recoverable failures (PRD §21)
MAX_ACTION_RETRIES = 3

# Error categories per PRD §46
class ErrorCode:
    CANCELLED = "CANCELLED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    BROWSER_START_FAILED = "BROWSER_START_FAILED"
    PAGE_LOAD_FAILED = "PAGE_LOAD_FAILED"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    ACTION_FAILED = "ACTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    NETWORK_ERROR = "NETWORK_ERROR"
    APPLICATION_ERROR = "APPLICATION_ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ExecutionError(Exception):
    """Execution runner error with structured info."""

    def __init__(self, message: str, error_code: str = "", state: str = ""):
        self.message = message
        self.error_code = error_code
        self.state = state
        super().__init__(message)


class FlowRunner:
    """Deterministic flow execution runner.

    Lifecycle:
        1. Load execution, flow, project, credentials
        2. Transition through states: QUEUED → INITIALIZING → BROWSER_READY → RUNNING
        3. For each step: observe → execute → verify (if needed)
        4. Verify final success condition
        5. Transition to COMPLETED or FAILED
        6. Cleanup browser

    Guarantees:
        - Never leaves execution stuck in RUNNING
        - Always transitions to terminal state on exit
        - Events persisted throughout execution
    """

    async def execute(
        self,
        execution_id: uuid.UUID,
        flow_steps: list[dict],
        success_condition: dict | None = None,
        credential_store: CredentialStore | None = None,
        target_url: str = "",
        event_recorder: Callable | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Execute a flow.

        Args:
            execution_id: Unique ID for this execution.
            flow_steps: List of action dicts to execute.
            success_condition: Verification condition for success.
            credential_store: Optional credential store for auth.
            target_url: Initial URL to navigate to.
            event_recorder: Optional callable for persisting events.
            timeout_seconds: Optional override for execution timeout.

        Returns:
            Execution result with events, observations, verification.
        """
        effective_timeout = timeout_seconds or EXECUTION_TIMEOUT_SECONDS

        try:
            result = await asyncio.wait_for(
                self._execute_inner(
                    execution_id, flow_steps, success_condition,
                    credential_store, target_url, event_recorder,
                ),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("Execution %s timed out after %ds", execution_id, effective_timeout)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "error": f"Execution timed out after {effective_timeout}s",
                "error_code": ErrorCode.EXECUTION_TIMEOUT,
                "events": [],
                "observations": [],
                "state": ExecutionState.FAILED.value,
            }

    async def _execute_inner(
        self,
        execution_id: uuid.UUID,
        flow_steps: list[dict],
        success_condition: dict | None,
        credential_store: CredentialStore | None,
        target_url: str,
        event_recorder: Callable | None,
    ) -> dict[str, Any]:
        """Inner execution logic (without timeout wrapper)."""
        ctx = ExecutionContext(
            execution_id=str(execution_id),
            target_url=target_url,
            credentials=credential_store or CredentialStore(),
        )

        # Step 1: QUEUED
        ctx.transition(ExecutionState.QUEUED)
        ctx.record_event(EventTypes.EXECUTION_QUEUED, {"execution_id": str(execution_id)})
        await self._emit_events(ctx, event_recorder)

        # Step 2: INITIALIZING
        ctx.transition(ExecutionState.INITIALIZING)
        ctx.record_event(EventTypes.EXECUTION_INITIALIZING, {})
        await self._emit_events(ctx, event_recorder)

        browser = BrowserSession()
        exec_id = str(execution_id)
        frame_task: asyncio.Task | None = None
        nav_unbind: Callable[[], None] | None = None
        try:
            # Step 3: Start browser
            await browser.start()
            ctx.transition(ExecutionState.BROWSER_READY)
            ctx.record_event(EventTypes.BROWSER_STARTED, {"browser": "chromium"})
            await self._emit_events(ctx, event_recorder)

            # Observe URL/title changes for the viewport (framenavigated)
            nav_unbind = self._bind_nav_observer(browser, exec_id)

            # Continuous frame producer — bounded FPS, cross-process via Redis
            frame_task = asyncio.create_task(
                self._frame_producer(browser, exec_id)
            )

            # Step 4: RUNNING
            ctx.transition(ExecutionState.RUNNING)
            ctx.started_at = datetime.now(timezone.utc)
            ctx.record_event(EventTypes.EXECUTION_STARTED, {"started_at": ctx.started_at.isoformat()})
            await self._emit_events(ctx, event_recorder)
            await publish_state(exec_id, "executing", browser.page.url, browser.page.url and "")

            # Step 5: Navigate to initial URL
            if target_url:
                await browser.navigate(target_url)
                await publish_state(exec_id, "navigating", target_url, "")
                ss_data = await self._capture_live_snapshot(browser, exec_id, state="navigating")
                page_payload: dict[str, Any] = {"url": target_url, **ss_data}
                ctx.record_event(EventTypes.PAGE_LOADED, page_payload)
                ctx.record_event(EventTypes.BROWSER_SCREENSHOT, ss_data)
                await self._emit_events(ctx, event_recorder)

            # Step 6: Execute steps
            action_executor = ActionExecutor(
                browser.page,
                event_recorder=None,
                credential_store=credential_store,
            )
            verifier = Verifier(browser.page)

            for i, step in enumerate(flow_steps):
                # Cancellation gate — checked at every step boundary
                if await is_cancel_requested(exec_id):
                    logger.info("Execution %s cancelled by user at step %d", execution_id, i)
                    ctx.record_event(EventTypes.EXECUTION_CANCELLED, {
                        "step": i,
                        "reason": "user_requested",
                    })
                    await self._emit_events(ctx, event_recorder)
                    # Persist CANCELLED on the execution row
                    try:
                        if event_recorder is not None and await self._execution_row_exists(uuid.UUID(exec_id)):
                            from app.infrastructure.database.session import async_session_factory
                            from app.modules.executions.models import ExecutionStatus
                            from app.modules.executions.repository import ExecutionRepository
                            async with async_session_factory() as cancel_db:
                                cancel_repo = ExecutionRepository(cancel_db)
                                await cancel_repo.update_status(
                                    uuid.UUID(exec_id), ExecutionStatus.CANCELLED
                                )
                                await cancel_db.commit()
                    except Exception as cancel_err:
                        logger.warning("Failed to persist CANCELLED status: %s", cancel_err)
                    return {
                        "success": False,
                        "execution_id": str(execution_id),
                        "error": "Execution cancelled by user",
                        "error_code": ErrorCode.CANCELLED,
                        "events": ctx.events,
                        "observations": ctx.observations,
                        "state": "CANCELLED",
                    }

                # Pause gate before each step — drain input while paused
                await self._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
                ctx.current_step_index = i
                await publish_state(exec_id, "executing", browser.page.url, "")
                try:
                    await self._capture_live_snapshot(browser, exec_id, step_index=i, state="observing")
                except Exception:
                    pass
                await self._execute_step_with_retry(ctx, browser, action_executor, step, i, event_recorder)
                # Drain any human input queued mid-step
                await self._process_user_input(browser, exec_id)
                # Pause gate after step
                await self._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
                try:
                    await self._capture_live_snapshot(browser, exec_id, step_index=i, state="executing")
                except Exception:
                    pass

            # Step 7: Verify final success condition
            ctx.transition(ExecutionState.VERIFYING)
            ctx.record_event(EventTypes.VERIFICATION_STARTED, {"condition": success_condition})
            await self._emit_events(ctx, event_recorder)

            if success_condition:
                verification = await verifier.verify(success_condition)
            else:
                from app.engine.verification.verifier import VerificationResult, VerificationCheck
                verification = VerificationResult(
                    passed=False,
                    checks=[VerificationCheck(
                        type="no_condition",
                        passed=False,
                        message="No success condition defined — mission cannot be verified",
                    )]
                )

            ctx.record_event(EventTypes.VERIFICATION_PASSED, verification.to_dict())
            await self._emit_events(ctx, event_recorder)

            if not verification.passed:
                # Determine appropriate status based on failure reason
                failed_checks = [c for c in verification.checks if not c.passed]
                error_messages = [c.message for c in failed_checks]
                error_str = "; ".join(error_messages)

                # Fail-closed condition problems (missing/unknown/malformed/vacuous
                # condition) mean the outcome could not be established — UNVERIFIED,
                # not FAILED. The actions may have succeeded; we just cannot prove it.
                UNVERIFIED_CONDITION_TYPES = {
                    "no_condition",
                    "empty_condition",
                    "unknown_condition",
                    "malformed_condition",
                    "vacuous_condition",
                }
                is_unverified = all(
                    c.type in UNVERIFIED_CONDITION_TYPES for c in failed_checks
                )

                # Check if we're stuck on an auth page
                is_auth_blocked = any(
                    "still on auth" in msg.lower() or "url_changed_from" in c.type
                    for c, msg in zip(failed_checks, error_messages)
                )
                # Check if we're on a blank/error page
                is_page_error = any(
                    "page_loaded" in c.type and not c.passed
                    for c in failed_checks
                )

                if is_unverified:
                    # Actions completed but the outcome could not be verified
                    ctx.transition(ExecutionState.COMPLETED)
                    ctx.completed_at = datetime.now(timezone.utc)
                    ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
                        "completed_at": ctx.completed_at.isoformat(),
                        "verification_status": "unverified",
                        "message": "Actions completed but mission could not be verified",
                        "reason": error_str or "No success condition was defined",
                    })
                    await self._emit_events(ctx, event_recorder)
                    return {
                        "success": False,
                        "execution_id": str(execution_id),
                        "error": "Actions completed but no success condition was defined",
                        "error_code": "UNVERIFIED",
                        "events": ctx.events,
                        "observations": ctx.observations,
                        "verification": verification.to_dict(),
                        "state": ExecutionState.COMPLETED.value,
                    }
                elif is_auth_blocked:
                    error_code = "AUTH_BLOCKED"
                    final_status = ExecutionState.FAILED
                elif is_page_error:
                    error_code = ErrorCode.PAGE_LOAD_FAILED
                    final_status = ExecutionState.FAILED
                else:
                    error_code = ErrorCode.VERIFICATION_FAILED
                    final_status = ExecutionState.FAILED

                raise ExecutionError(
                    f"Verification failed: {error_str}",
                    error_code=error_code,
                )

            # Step 8: Capture evidence
            await self._capture_evidence(ctx, browser, verification, event_recorder)

            # Step 9: COMPLETED
            ctx.transition(ExecutionState.COMPLETED)
            ctx.completed_at = datetime.now(timezone.utc)
            ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
                "completed_at": ctx.completed_at.isoformat(),
                "duration_ms": int((ctx.completed_at - ctx.started_at).total_seconds() * 1000),
            })
            await self._emit_events(ctx, event_recorder)

            return {
                "success": True,
                "execution_id": str(execution_id),
                "events": ctx.events,
                "observations": ctx.observations,
                "verification": verification.to_dict(),
                "final_url": browser.page.url,
                "final_title": await browser.page.title(),
                "duration_ms": int((ctx.completed_at - ctx.started_at).total_seconds() * 1000),
            }

        except Exception as e:
            # Step 9: FAILED - always transition to terminal state
            if ctx.state not in (ExecutionState.COMPLETED, ExecutionState.FAILED):
                try:
                    ctx.transition(ExecutionState.FAILED)
                except Exception as transition_err:
                    logger.warning("State transition to FAILED failed: %s", transition_err)
                    ctx.state = ExecutionState.FAILED

            ctx.completed_at = datetime.now(timezone.utc)
            ctx.record_error(str(e))
            error_code = getattr(e, "error_code", ErrorCode.UNKNOWN)
            ctx.record_event(EventTypes.EXECUTION_FAILED, {
                "error": str(e),
                "error_code": error_code,
                "completed_at": ctx.completed_at.isoformat(),
            })
            await self._emit_events(ctx, event_recorder)

            # Capture failure evidence: screenshot of failure state
            try:
                await self._capture_failure_evidence(ctx, browser, str(e), error_code, event_recorder)
            except Exception as ev_err:
                logger.warning("Failure evidence capture failed: %s", ev_err)

            logger.warning("Execution %s failed: %s", execution_id, e)

            return {
                "success": False,
                "execution_id": str(execution_id),
                "error": str(e),
                "error_code": error_code,
                "events": ctx.events,
                "observations": ctx.observations,
                "state": ctx.state.value,
            }

        finally:
            # Step 10: Cleanup - stop frame producer, unbind nav, close browser, clear control
            if frame_task is not None:
                frame_task.cancel()
                try:
                    await frame_task
                except asyncio.CancelledError:
                    pass
                except Exception as fe:
                    logger.debug("Frame producer teardown: %s", fe)
            if nav_unbind is not None:
                try:
                    nav_unbind()
                except Exception:
                    pass
            try:
                await cleanup_control(exec_id)
            except Exception as ce:
                logger.debug("Control cleanup failed: %s", ce)
            try:
                await browser.close()
                ctx.record_event(EventTypes.BROWSER_CLOSED, {})
            except Exception as e:
                logger.warning("Error closing browser: %s", e)

    async def _frame_producer(
        self,
        browser: BrowserSession,
        execution_id: str,
        interval: float = FRAME_INTERVAL_SECONDS,
    ) -> None:
        """Publish viewport frames at a bounded rate until cancelled.

        Latest-wins: Redis pub/sub drops slow consumers; frontend Queue(maxsize=1)
        discards stale frames. Never persists frames.
        """
        state = "observing"
        while True:
            try:
                page = browser.page
                if page is None or page.is_closed():
                    await asyncio.sleep(interval)
                    continue
                # Prefer higher-level state if control is human
                ctrl = await get_control_state(execution_id)
                if ctrl in ("human", "paused"):
                    state = "paused"
                ss_bytes = await page.screenshot(type="jpeg", quality=45, timeout=2000)
                if ss_bytes:
                    await publish_frame(execution_id, ss_bytes, state)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug("Frame producer tick failed: %s", e)
            await asyncio.sleep(interval)

    def _bind_nav_observer(
        self,
        browser: BrowserSession,
        execution_id: str,
    ) -> Callable[[], None]:
        """Publish url/title on framenavigated. Returns unbind callable."""
        page = browser.page

        def _on_nav(nav_page) -> None:
            try:
                url = nav_page.url or ""
                asyncio.get_running_loop().create_task(
                    self._publish_nav(execution_id, nav_page, url)
                )
            except Exception:
                pass

        try:
            page.on("framenavigated", _on_nav)
        except Exception as e:
            logger.debug("Nav observer bind failed: %s", e)
            return lambda: None

        def _unbind() -> None:
            try:
                page.remove_listener("framenavigated", _on_nav)
            except Exception:
                pass

        return _unbind

    async def _publish_nav(self, execution_id: str, nav_page, url: str) -> None:
        title = ""
        try:
            if nav_page is not None and not nav_page.is_closed():
                title = (await nav_page.title()) or ""
        except Exception:
            pass
        try:
            await publish_state(execution_id, "navigating", url, title, loading=True)
        except Exception:
            pass

    async def _capture_live_snapshot(
        self,
        browser: BrowserSession,
        execution_id: str,
        step_index: int | None = None,
        action_type: str | None = None,
        state: str = "observing",
    ) -> dict[str, Any]:
        """Capture and publish a live frame. Does NOT persist to storage (ephemeral)."""
        snapshot_payload: dict[str, Any] = {
            "url": browser.page.url,
        }
        if step_index is not None:
            snapshot_payload["step"] = step_index
        if action_type:
            snapshot_payload["action"] = action_type

        try:
            ss_bytes = await browser.page.screenshot(type="jpeg", quality=45, timeout=2000)
            if ss_bytes:
                await publish_frame(execution_id, ss_bytes, state)
        except Exception as ss_err:
            logger.debug("Live frame capture failed: %s", ss_err)

        return snapshot_payload

    async def _capture_evidence_screenshot(
        self,
        browser: BrowserSession,
        execution_id: str,
        ctx: ExecutionContext,
        title: str = "Evidence",
        description: str = "",
    ) -> dict[str, Any]:
        """Capture and persist an evidence screenshot (separate from live frames)."""
        snapshot_payload: dict[str, Any] = {
            "url": browser.page.url,
        }
        try:
            ss_bytes = await browser.page.screenshot(type="jpeg", quality=70)
            if ss_bytes:
                storage_res = screenshot_storage.upload_execution_screenshot(
                    execution_id=execution_id,
                    screenshot_bytes=ss_bytes,
                    url=browser.page.url,
                    content_type="image/jpeg",
                )
                if storage_res.get("screenshot_url"):
                    snapshot_payload["screenshot_url"] = storage_res["screenshot_url"]
                    snapshot_payload["screenshot_key"] = storage_res.get("screenshot_key")
        except Exception as ss_err:
            logger.debug("Evidence screenshot capture failed: %s", ss_err)

        return snapshot_payload

    async def _process_user_input(
        self,
        browser: BrowserSession,
        execution_id: str,
    ) -> None:
        """Process any pending user input from the control channel."""
        try:
            pending = await get_pending_input(execution_id)
            for msg in pending:
                kind = msg.get("kind", "")
                try:
                    if kind == "click":
                        x, y = msg.get("x", 0), msg.get("y", 0)
                        await browser.page.mouse.click(x, y)
                    elif kind == "mouse_down":
                        await browser.page.mouse.down(button="left" if msg.get("button", 0) == 0 else "right")
                    elif kind == "mouse_up":
                        await browser.page.mouse.up(button="left" if msg.get("button", 0) == 0 else "right")
                    elif kind == "mouse_move":
                        x, y = msg.get("x", 0), msg.get("y", 0)
                        await browser.page.mouse.move(x, y)
                    elif kind == "scroll":
                        dx, dy = msg.get("delta_x", 0), msg.get("delta_y", 0)
                        await browser.page.mouse.wheel(dx, dy)
                    elif kind == "key_down":
                        key = msg.get("key", "")
                        if key and len(key) == 1:
                            await browser.page.keyboard.down(key)
                    elif kind == "key_up":
                        key = msg.get("key", "")
                        if key and len(key) == 1:
                            await browser.page.keyboard.up(key)
                    elif kind == "type":
                        text = msg.get("text", "")
                        if text:
                            await browser.page.keyboard.type(text)
                    elif kind == "nav_back":
                        await browser.page.go_back(wait_until="domcontentloaded", timeout=10000)
                    elif kind == "nav_forward":
                        await browser.page.go_forward(wait_until="domcontentloaded", timeout=10000)
                    elif kind == "nav_reload":
                        await browser.page.reload(wait_until="domcontentloaded", timeout=15000)
                    logger.debug("User input processed: %s", kind)
                except Exception as e:
                    logger.warning("User input failed: %s: %s", kind, e)
        except Exception as e:
            logger.debug("Failed to get pending input: %s", e)

    async def _check_and_handle_pause(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        execution_id: str,
        event_recorder: Callable | None,
    ) -> bool:
        """Gate for human takeover.

        While control is human: drain input → apply → publish frame → check
        resume, every PAUSE_POLL_SECONDS. Never blocks without draining input.
        Transitions: RUNNING → PAUSED → HUMAN_CONTROLLED → RESUMING → RUNNING.
        """
        is_paused = await check_pause(execution_id)
        if not is_paused:
            return False

        logger.info("Execution %s pausing for user takeover", execution_id)
        ctx.transition(ExecutionState.PAUSED)
        ctx.control_state = "human"
        # Engine state machine may not expose HUMAN_CONTROLLED — record as event/state attr
        try:
            from app.engine.execution.state import ExecutionState as ES
            if hasattr(ES, "HUMAN_CONTROLLED"):
                ctx.transition(ES.HUMAN_CONTROLLED)
        except Exception:
            pass
        ctx.record_event(EventTypes.EXECUTION_PAUSED, {"reason": "user_takeover"})
        ctx.record_event(EventTypes.EXECUTION_HUMAN_CONTROLLED, {"control": "human"})
        await publish_state(execution_id, "paused", browser.page.url, "", control="human")
        await self._emit_events(ctx, event_recorder)

        try:
            await self._capture_live_snapshot(browser, execution_id, state="paused")
        except Exception:
            pass

        # Poll loop: drain input, apply, frame, check resume — never block without input
        loop = asyncio.get_event_loop()
        start = loop.time()
        resumed = False
        while True:
            await self._process_user_input(browser, execution_id)
            ctrl = await get_control_state(execution_id)
            if ctrl == "agent":
                resumed = True
                break
            if loop.time() - start >= PAUSE_TIMEOUT_SECONDS:
                logger.warning("Execution %s pause timed out after %ds", execution_id, PAUSE_TIMEOUT_SECONDS)
                resumed = False
                break
            try:
                await self._capture_live_snapshot(browser, execution_id, state="paused")
            except Exception:
                pass
            await asyncio.sleep(PAUSE_POLL_SECONDS)

        if not resumed:
            # Auto-resume on timeout so execution never sticks in PAUSED
            from app.engine.execution.control import set_control_state
            await set_control_state(execution_id, "agent")

        logger.info("Execution %s resuming after user takeover", execution_id)
        ctx.transition(ExecutionState.RESUMING)
        ctx.control_state = "agent"
        ctx.record_event(EventTypes.EXECUTION_RESUMED, {})
        await publish_state(execution_id, "resuming", browser.page.url, "", control="agent")
        await self._emit_events(ctx, event_recorder)

        # Re-observe after takeover
        try:
            observation = await browser.observe()
            ctx.record_observation(observation)
            ctx.record_event(EventTypes.AGENT_OBSERVED, {
                "step": ctx.current_step_index,
                "observation": observation,
                "post_takeover": True,
            })
            await self._emit_events(ctx, event_recorder)
        except Exception as e:
            logger.warning("Post-takeover observation failed: %s", e)

        ctx.transition(ExecutionState.RUNNING)
        await publish_state(execution_id, "executing", browser.page.url, "", control="agent")
        return True

    # Actions whose failure may already have had side effects — never blindly
    # re-executed. A retried click on 'Delete' or a form submit can double-apply.
    NON_RETRYABLE_ACTION_TYPES = {"click"}
    DESTRUCTIVE_ACTION_TEXT = (
        "delete", "remove", "destroy", "purge", "drop",
        "confirm", "pay", "checkout", "purchase", "place order", "submit payment",
    )

    @staticmethod
    def _is_destructive_step(step: dict) -> bool:
        """Heuristically detect steps whose retry could cause real damage."""
        step_type = (step.get("type") or step.get("action") or "").lower()
        texts = [
            str(step.get("description", "") or ""),
            str(step.get("name", "") or ""),
            str(step.get("text", "") or ""),
        ]
        target = step.get("target")
        if isinstance(target, dict):
            texts.append(str(target.get("text", "") or ""))
            texts.append(str(target.get("css", "") or ""))
        elif isinstance(target, str):
            texts.append(target)
        combined = (step_type + " " + " ".join(texts)).lower()
        return any(kw in combined for kw in FlowRunner.DESTRUCTIVE_ACTION_TEXT)

    async def _execute_step_with_retry(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        action_executor: ActionExecutor,
        step: dict,
        step_index: int,
        event_recorder: Callable | None,
    ) -> None:
        """Execute a step with deterministic, strategy-aware recovery (PRD §21).

        Recovery ladder for target_not_found: re-observe the page, then retry —
        the observation itself refreshes Playwright's element handles, which is
        the deterministic equivalent of "try the next resolution strategy".

        Never retries:
        - clicks (side effects already applied on partial failure)
        - any step matching destructive keywords (delete/confirm/pay/...)
        - validation_error, credential_error, verification_failed
        """
        raw_type = (step.get("type") or step.get("action") or "").lower() if isinstance(step, dict) else ""
        destructive = self._is_destructive_step(step) if isinstance(step, dict) else False

        # Clicks and destructive actions get exactly one attempt — a failed
        # click may already have triggered navigation or state changes.
        attempts = 1 if (raw_type in self.NON_RETRYABLE_ACTION_TYPES or destructive) else MAX_ACTION_RETRIES

        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                await self._execute_step(ctx, browser, action_executor, step, step_index, event_recorder)
                return  # Success
            except ExecutionError as e:
                last_error = e
                recoverable = e.error_code in (ErrorCode.TARGET_NOT_FOUND, ErrorCode.ACTION_FAILED)
                if not recoverable or attempt >= attempts:
                    raise

                if e.error_code == ErrorCode.TARGET_NOT_FOUND:
                    # Re-observe before retrying: DOM may have re-rendered and
                    # the previous snapshot was stale.
                    try:
                        observation = await browser.observe()
                        ctx.record_observation(observation)
                    except Exception:
                        pass

                logger.info(
                    "Step %d failed (attempt %d/%d), retrying: %s",
                    step_index, attempt, attempts, e.message,
                )
                ctx.record_event(EventTypes.RECOVERY_STARTED, {
                    "step": step_index,
                    "attempt": attempt,
                    "error_code": e.error_code,
                })
                await self._emit_events(ctx, event_recorder)
                # Brief pause before retry to allow UI to update
                await asyncio.sleep(0.5)
        # Should not reach here, but safety net
        if last_error:
            raise last_error

    async def _execute_step(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        action_executor: ActionExecutor,
        step: dict,
        step_index: int,
        event_recorder: Callable | None,
    ) -> None:
        """Execute a single step in the flow."""
        # Observe before action
        ctx.transition(ExecutionState.OBSERVING)
        observation = await browser.observe()
        ctx.record_observation(observation)
        ctx.record_event(EventTypes.AGENT_OBSERVED, {
            "step": step_index,
            "observation": observation,
        })
        await self._emit_events(ctx, event_recorder)

        # Map old/string format to new format if needed
        raw_action = self._normalize_step(step, target_url=ctx.target_url)
        action_type = raw_action.get("type", "")

        ctx.record_event(EventTypes.ACTION_STARTED, {
            "step": step_index,
            "type": action_type,
            "target": raw_action.get("target"),
        })
        await self._emit_events(ctx, event_recorder)

        result = await action_executor.execute(
            raw_action,
            execution_id=uuid.UUID(ctx.execution_id) if ctx.execution_id else None,
        )

        if not result["success"]:
            # Capture failure snapshot so UI displays the browser state at failure
            try:
                fail_ss = await self._capture_live_snapshot(
                    browser, str(ctx.execution_id), step_index=step_index, action_type=action_type, state="failed"
                )
                ctx.record_event(EventTypes.BROWSER_SCREENSHOT, {**fail_ss, "failed": True})
                await self._emit_events(ctx, event_recorder)
            except Exception:
                pass
            error_type = result.get("error", {}).get("type", "action_failed")
            error_code = _map_error_code(error_type)
            raise ExecutionError(
                f"Action failed at step {step_index}: {result.get('error', {}).get('message', 'Unknown')}",
                error_code=error_code,
            )

        # No per-action screenshot — evidence screenshots are captured at
        # verification.passed, verification.failed, execution.completed, and
        # execution.failed in _capture_evidence. Action completed payload
        # includes the current URL for lightweight state tracking.
        action_completed_payload: dict[str, Any] = {
            "step": step_index,
            "type": action_type,
            "result": result.get("result"),
            "url": browser.page.url,
        }

        ctx.record_event(EventTypes.ACTION_COMPLETED, action_completed_payload)
        await self._emit_events(ctx, event_recorder)

    def _normalize_step(self, step: dict | str, target_url: str = "") -> dict:
        """Normalize step format to action executor format.

        Handles:
        1. String format: "Click Submit", "Navigate to https://..."
        2. New format: {type, target, value} — pass through with target validation
        3. Old format: {action, selector, value} — convert
        4. Description format: {action, description} — infer type and target
        """
        if isinstance(step, str):
            step_text = step.strip()
            action_type = self._infer_action_type(step_text)
            if action_type == "navigate":
                url_match = re.search(r"https?://\S+", step_text)
                val = url_match.group(0) if url_match else target_url
                return {"type": "navigate", "value": val, "target": {}}

            clean_target = re.sub(
                r"^(?:click|navigate to|open|go to|press|select|type into|type|verify|check|uncheck)\s+",
                "",
                step_text,
                flags=re.IGNORECASE,
            ).strip()

            target = {}
            if clean_target.startswith("#") or clean_target.startswith(".") or clean_target.startswith("["):
                target["css"] = clean_target
            else:
                target["text"] = clean_target or "button"

            return {"type": action_type, "target": target}

        if not isinstance(step, dict):
            return {"type": "wait", "value": "1.0", "target": {}}

        # Extract target from various candidate fields
        raw_target = step.get("target")
        target = {}
        if isinstance(raw_target, dict) and raw_target:
            target = raw_target.copy()
        elif isinstance(raw_target, str) and raw_target.strip() and raw_target.strip() != "[object Object]":
            # Journey builders emit targets as plain selector strings
            # (e.g. {"type": "click", "target": "button:has-text('Search')"}).
            # Dropping them silently made every generated mission fall back to
            # clicking the first generic button on the page.
            target["css"] = raw_target.strip()

        selector = step.get("selector", "")
        if selector == "[object Object]":
            selector = ""
        if selector and not target.get("css"):
            target["css"] = selector
        if target.get("css") == "[object Object]":
            target.pop("css", None)
        if step.get("test_id") and not target.get("test_id"):
            target["test_id"] = step["test_id"]
        if step.get("name") and not target.get("name"):
            target["name"] = step["name"]
        if step.get("text") and not target.get("text"):
            target["text"] = step["text"]
        if step.get("label") and not target.get("label"):
            target["label"] = step["label"]
        if step.get("role") and not target.get("role"):
            target["role"] = step["role"]

        raw_action = step.get("action", step.get("type", ""))
        if raw_action == "[object Object]":
            raw_action = ""
        value = step.get("value", "")
        if value == "[object Object]":
            value = ""
        description = step.get("description", "")
        if description == "[object Object]":
            description = ""

        # Check if raw_action is a valid ActionType
        valid_action_types = {t.value for t in ActionType}
        if raw_action in valid_action_types:
            action_type = raw_action
        elif raw_action:
            action_type = self._infer_action_type(raw_action)
        elif description:
            action_type = self._infer_action_type(description)
        elif value and _is_url_like(value):
            action_type = "navigate"
        else:
            action_type = "click"

        # If action requires target and target is still empty, derive from description/action
        actions_needing_target = {"click", "type", "clear", "select", "check", "uncheck", "upload"}
        if action_type in actions_needing_target and not target:
            candidate_text = description or (raw_action if raw_action not in valid_action_types else "")
            if candidate_text and candidate_text != "[object Object]":
                clean_target = re.sub(
                    r"^(?:click|navigate to|open|go to|press|select|type into|type|verify|check|uncheck)\s+",
                    "",
                    candidate_text,
                    flags=re.IGNORECASE,
                ).strip()
                if clean_target and clean_target != "[object Object]":
                    if clean_target.startswith("#") or clean_target.startswith(".") or (clean_target.startswith("[") and clean_target.endswith("]")):
                        target["css"] = clean_target
                    else:
                        target["text"] = clean_target

            if not target:
                target["css"] = "button, a, input, [role='button']"

        if action_type == "navigate" and not value:
            value = step.get("url") or target_url

        result = {"type": action_type, "target": target}
        if value:
            result["value"] = value
        if "credential_id" in step:
            result["credential_id"] = step["credential_id"]
        if "credential_field" in step:
            result["credential_field"] = step["credential_field"]

        return result

    @staticmethod
    def _infer_action_type(text: str) -> str:
        """Infer browser action type from descriptive text.

        Maps common step descriptions to executable action types.
        """
        lower = text.lower().strip()

        # Navigate patterns
        if any(kw in lower for kw in ["navigate", "open", "go to", "visit", "load"]):
            return "navigate"
        if _is_url_like(text):
            return "navigate"

        # Click patterns
        if any(kw in lower for kw in ["click", "press", "tap", "submit", "sign in", "log in", "login"]):
            return "click"

        # Select patterns
        if any(kw in lower for kw in ["select", "choose"]):
            return "select"

        # Check / Uncheck
        if "uncheck" in lower:
            return "uncheck"
        if "check" in lower:
            return "check"

        # Type patterns
        if any(kw in lower for kw in ["type", "enter", "fill", "input", "write", "put"]):
            return "type"

        # Scroll patterns
        if any(kw in lower for kw in ["scroll", "swipe"]):
            return "scroll"

        # Wait patterns
        if any(kw in lower for kw in ["wait", "pause", "sleep"]):
            return "wait"

        # Press key patterns
        if any(kw in lower for kw in ["press key", "hit key", "keyboard"]):
            return "press"

        # Default: click (most common interaction)
        return "click"

    async def _capture_evidence(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        verification,
        event_recorder: Callable | None,
    ) -> None:
        """Capture evidence after successful verification.

        Creates:
        1. Verification evidence (structured proof)
        2. Screenshot evidence (visual proof of final state)
        Never crashes execution on storage/DB failure.
        Standalone/test runs (no event_recorder) skip persistence entirely.
        """
        if event_recorder is None:
            return

        execution_id = uuid.UUID(ctx.execution_id)
        try:
            await asyncio.wait_for(
                self._capture_evidence_inner(
                    ctx, browser, verification, event_recorder, execution_id
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Evidence capture timed out for %s", execution_id)
        except Exception as e:
            logger.warning("Evidence capture overall failed: %s", e)

    async def _execution_row_exists(self, execution_id: uuid.UUID) -> bool:
        """True when the execution has a DB row (real worker runs only)."""
        import app.modules.users.models  # noqa: F401
        import app.modules.projects.models  # noqa: F401
        import app.modules.flows.models  # noqa: F401
        import app.modules.executions.models  # noqa: F401
        import app.modules.executions.event_model  # noqa: F401
        import app.modules.executions.evidence_model  # noqa: F401
        from sqlalchemy import select

        from app.infrastructure.database.session import async_session_factory
        from app.modules.executions.models import Execution

        try:
            async with asyncio.timeout(2.0):
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(Execution.id).where(Execution.id == execution_id)
                    )
                    return result.scalar_one_or_none() is not None
        except (TimeoutError, asyncio.TimeoutError):
            logger.debug("Existence check timed out for %s", execution_id)
            return False
        except Exception as e:
            logger.debug("Existence check failed for %s: %s", execution_id, e)
            return False

    async def _capture_evidence_inner(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        verification,
        event_recorder: Callable | None,
        execution_id: uuid.UUID,
    ) -> None:
        try:
            if not await self._execution_row_exists(execution_id):
                logger.debug(
                    "Skip evidence for %s — no execution row (standalone run)",
                    execution_id,
                )
                return

            from app.modules.executions.evidence_service import EvidenceService
            from app.infrastructure.database.session import async_session_factory

            async with async_session_factory() as db:
                evidence_service = EvidenceService(db)

                # 1. Create verification evidence from checks
                if verification and verification.checks:
                    passed_checks = [c for c in verification.checks if c.passed]
                    if passed_checks:
                        check_descriptions = [c.message for c in passed_checks if c.message]
                        title = "Verification passed"
                        description = "; ".join(check_descriptions) if check_descriptions else "All checks passed"

                        try:
                            await evidence_service.create_verification_evidence(
                                execution_id=execution_id,
                                title=title,
                                description=description,
                                checks=[c.to_dict() for c in verification.checks],
                            )
                        except Exception as e:
                            logger.warning("Could not persist verification evidence: %s", e)

                # 2. Capture screenshot of final verified state
                try:
                    screenshot_bytes = await browser.page.screenshot(type="png")
                    if screenshot_bytes:
                        await evidence_service.capture_screenshot(
                            execution_id=execution_id,
                            screenshot_bytes=screenshot_bytes,
                            title="Verified browser state",
                            description="Browser state after successful verification",
                        )
                        # Also upload to public screenshot_storage for instant live UI rendering
                        storage_res = screenshot_storage.upload_execution_screenshot(
                            execution_id=str(execution_id),
                            screenshot_bytes=screenshot_bytes,
                            url=browser.page.url,
                            content_type="image/png",
                        )
                        ss_event_data: dict[str, Any] = {
                            "title": "Verified browser state",
                            "url": browser.page.url,
                        }
                        if storage_res.get("screenshot_url"):
                            ss_event_data["screenshot_url"] = storage_res["screenshot_url"]
                            ss_event_data["screenshot_key"] = storage_res.get("screenshot_key")
                        ctx.record_event(EventTypes.BROWSER_SCREENSHOT, ss_event_data)
                        await self._emit_events(ctx, event_recorder)
                except Exception as e:
                    logger.warning("Evidence screenshot capture failed: %s", e)
                    ctx.record_event(EventTypes.EVIDENCE_FAILED, {
                        "type": "SCREENSHOT",
                        "error": "Screenshot capture failed",
                    })

                try:
                    await db.commit()
                except Exception as e:
                    logger.warning("Could not commit evidence session: %s", e)

        except Exception as e:
            logger.warning("Evidence capture overall failed: %s", e)

    async def _capture_failure_evidence(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        error_message: str,
        error_code: str,
        event_recorder: Callable | None,
    ) -> None:
        """Capture evidence on execution failure — screenshot of failure state."""
        if event_recorder is None:
            return

        execution_id = uuid.UUID(ctx.execution_id)
        try:
            await asyncio.wait_for(
                self._capture_failure_evidence_inner(
                    ctx, browser, error_message, error_code, event_recorder, execution_id
                ),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            logger.warning("Failure evidence capture timed out for %s", execution_id)
        except Exception as e:
            logger.warning("Failure evidence capture overall failed: %s", e)

    async def _capture_failure_evidence_inner(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        error_message: str,
        error_code: str,
        event_recorder: Callable | None,
        execution_id: uuid.UUID,
    ) -> None:
        try:
            if not await self._execution_row_exists(execution_id):
                logger.debug(
                    "Skip failure evidence for %s — no execution row",
                    execution_id,
                )
                return

            from app.modules.executions.evidence_service import EvidenceService
            from app.infrastructure.database.session import async_session_factory

            async with async_session_factory() as db:
                evidence_service = EvidenceService(db)

                # Screenshot of failure state
                try:
                    screenshot_bytes = await browser.page.screenshot(type="png")
                    if screenshot_bytes:
                        await evidence_service.capture_screenshot(
                            execution_id=execution_id,
                            screenshot_bytes=screenshot_bytes,
                            title="Execution failed",
                            description=f"Browser state at failure: {error_message}",
                        )
                except Exception as e:
                    logger.warning("Failure screenshot capture failed: %s", e)

                try:
                    await db.commit()
                except Exception as e:
                    logger.warning("Could not commit failure evidence: %s", e)

        except Exception as e:
            logger.warning("Failure evidence capture overall failed: %s", e)

    async def _emit_events(
        self,
        ctx: ExecutionContext,
        event_recorder: Callable | None,
    ) -> None:
        """Emit any pending events to the recorder."""
        if not event_recorder:
            return

        # Emit all uncommitted events — skip failures, don't abort remaining
        while ctx.events:
            event = ctx.events[0]
            try:
                await event_recorder(
                    uuid.UUID(ctx.execution_id),
                    event["type"],
                    event.get("data", {}),
                )
                ctx.events.pop(0)
            except Exception as e:
                logger.warning("Failed to emit event %s, skipping: %s", event["type"], e)
                ctx.events.pop(0)


def _is_url_like(text: str) -> bool:
    """Check if text looks like a URL."""
    return bool(re.match(r"^https?://", text.strip()))


def _map_error_code(raw_error_type: str) -> str:
    """Map raw error types to structured PRD §46 error categories."""
    mapping = {
        "target_not_found": ErrorCode.TARGET_NOT_FOUND,
        "validation_error": ErrorCode.ACTION_FAILED,
        "credential_error": ErrorCode.AUTHENTICATION_FAILED,
        "execution_error": ErrorCode.ACTION_FAILED,
        "timeout": ErrorCode.EXECUTION_TIMEOUT,
        "network_error": ErrorCode.NETWORK_ERROR,
    }
    return mapping.get(raw_error_type, ErrorCode.UNKNOWN)
