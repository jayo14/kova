"""Deterministic execution runner.

Orchestrates the complete lifecycle of a flow execution:
load → queue → init browser → run steps → verify → complete/fail → cleanup

Never leaves execution stuck in RUNNING.
Always transitions to terminal state on exit.
"""

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

ALLOWED_NAMED_KEYS = {
    "Backspace",
    "Delete",
    "Enter",
    "Tab",
    "Escape",
    "ArrowUp",
    "ArrowDown",
    "ArrowLeft",
    "ArrowRight",
    "Home",
    "End",
    "PageUp",
    "PageDown",
    "Shift",
    "Control",
    "Alt",
    "Meta",
    "CapsLock",
}

from app.engine.browser.actions import ActionType
from app.engine.browser.executor import ActionExecutor
from app.engine.browser.session import BrowserSession
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

    def __init__(self) -> None:
        self._last_mouse_up: dict[str, tuple[float, int, int]] = {}
        self._emit_lock = asyncio.Lock()

    async def execute(
        self,
        execution_id: uuid.UUID,
        flow_steps: list[dict] | None = None,
        success_condition: dict | None = None,
        preconditions: dict | None = None,
        dependency_plan: list[dict] | None = None,
        credential_store: CredentialStore | None = None,
        target_url: str = "",
        event_recorder: Callable | None = None,
        timeout_seconds: int | None = None,
        objective: str | None = None,
        expected_outcome: str | None = None,
        fail_on_healed: bool | None = None,
        target_flow: Any | None = None,
        flows: list[Any] | None = None,
        persona: str = "default",
        current_state: dict[str, Any] | None = None,
        session_manager: Any | None = None,
        reset_strategy: str = "none",
        project: Any | None = None,
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
            objective: Optional natural language objective.
            expected_outcome: Optional natural language expected outcome.
            fail_on_healed: Optional flag to fail execution if AI healing was used.
            target_flow: Optional target Flow domain model.
            flows: Optional list of available Flow models for planning.
            persona: Active persona name (defaults to "default").
            current_state: Initial application state dictionary.
            session_manager: Optional SessionManager instance.
            reset_strategy: Contamination reset strategy ("none", "re_establish", "create_new", "skip_if_exists").
            project: Optional Project domain model for limits and safety configuration.

        Returns:
            Execution result with events, observations, verification, and current_state.
        """
        from app.config.settings import settings

        project_obj = project or getattr(target_flow, "project", None)
        limits = getattr(project_obj, "execution_limits", None) or {}
        max_duration = limits.get("max_duration_seconds") if isinstance(limits, dict) else getattr(limits, "max_duration_seconds", None)

        is_agent_run = bool(
            settings.AGENT_EXECUTION_ENABLED
            and (objective or (target_flow and getattr(target_flow, "objective", None)))
            and not flow_steps
            and not (target_flow and getattr(target_flow, "steps", None))
        )
        if is_agent_run:
            agent_cap = settings.AGENT_EXECUTION_MAX_DURATION_SECONDS
            effective_timeout = timeout_seconds or (min(max_duration, agent_cap) if max_duration else agent_cap)
        else:
            effective_timeout = timeout_seconds or (max_duration if max_duration else EXECUTION_TIMEOUT_SECONDS)
            if max_duration and timeout_seconds:
                effective_timeout = min(timeout_seconds, max_duration)

        try:
            result = await asyncio.wait_for(
                self._execute_inner(
                    execution_id, flow_steps, success_condition,
                    credential_store, target_url, event_recorder, preconditions, dependency_plan,
                    objective, expected_outcome, fail_on_healed,
                    target_flow, flows, persona, current_state, session_manager, reset_strategy,
                    project=project_obj,
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

    async def run(self, *args, **kwargs) -> dict[str, Any]:
        """Execute/run a flow with state-aware planning and prerequisite resolution."""
        return await self.execute(*args, **kwargs)

    async def _mark_unverified(
        self,
        ctx: ExecutionContext,
        execution_id: uuid.UUID | str,
        *,
        failure_category: str = "ai_proposal_rejected",
        error_message: str = "All AI-proposed steps failed validation; cannot execute.",
    ) -> None:
        """Mark execution as UNVERIFIED, record event, and persist to database."""
        try:
            ctx.transition(ExecutionState.COMPLETED)
        except Exception:
            pass
        ctx.completed_at = datetime.now(timezone.utc)
        ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
            "completed_at": ctx.completed_at.isoformat(),
            "verification_status": "unverified",
            "message": error_message,
            "failure_category": failure_category,
            "reason": error_message,
        })
        try:
            from app.infrastructure.database.session import async_session_factory
            from app.modules.executions.models import ExecutionStatus
            from app.modules.executions.repository import ExecutionRepository

            async with async_session_factory() as db:
                repo = ExecutionRepository(db)
                exec_uuid = uuid.UUID(str(execution_id))
                await repo.update_status(exec_uuid, ExecutionStatus.UNVERIFIED)
                await db.commit()
        except Exception as db_err:
            logger.debug("Failed to persist UNVERIFIED status for execution %s: %s", execution_id, db_err)

    async def _execute_via_agent_loop(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        verifier: Verifier,
        execution_id: uuid.UUID,
        target_url: str,
        objective: str,
        success_condition: dict | None,
        credential_store: CredentialStore | None,
        event_recorder: Callable | None,
        persona: str = "default",
        project: Any | None = None,
    ) -> dict[str, Any]:
        """Dispatch flow execution to the autonomous agent loop behind feature flag."""
        from app.config.settings import settings
        from app.engine.ai.executor import AgentExecutor
        from app.engine.ai.provider import get_ai_provider
        from app.engine.ai.reasoner import AgentReasoner

        ai_provider = get_ai_provider()
        reasoner = AgentReasoner(provider=ai_provider)

        safety_restrictions = getattr(project, "safety_restrictions", None) or getattr(ctx, "safety_restrictions", None)
        execution_limits = getattr(project, "execution_limits", None) or getattr(ctx, "execution_limits", None)

        max_dur = settings.AGENT_EXECUTION_MAX_DURATION_SECONDS
        if execution_limits:
            proj_max_dur = execution_limits.get("max_duration_seconds") if isinstance(execution_limits, dict) else getattr(execution_limits, "max_duration_seconds", None)
            if proj_max_dur:
                max_dur = min(max_dur, proj_max_dur)

        ctx.record_event(EventTypes.AGENT_LOOP_STARTED, {
            "objective": objective,
            "persona": persona,
            "max_duration_seconds": max_dur,
        })
        await self._emit_events(ctx, event_recorder)

        async def _agent_event_emitter(event_type: str, payload: dict) -> None:
            ctx.record_event(EventTypes.AGENT_LOOP_TURN, {
                "sub_event_type": event_type,
                **payload,
            })
            ctx.record_event(event_type, payload)
            await self._emit_events(ctx, event_recorder)

        agent_executor = AgentExecutor(
            execution_id=execution_id,
            reasoner=reasoner,
            email_provider=None,
            credential_store=credential_store,
            event_emitter=_agent_event_emitter,
            max_duration=float(max_dur),
            safety_restrictions=safety_restrictions,
        )

        outcome = await agent_executor.run(
            browser=browser,
            target_url=target_url,
            objective=objective,
        )

        ctx.record_event(EventTypes.AGENT_LOOP_OUTCOME, {
            "status": outcome.status,
            "reason": outcome.reason,
            "facts": outcome.facts,
            "failure_category": getattr(outcome, "failure_category", None),
        })
        await self._emit_events(ctx, event_recorder)

        # Translate AgentOutcome to ExecutionState
        if outcome.status == "COMPLETED":
            ctx.transition(ExecutionState.VERIFYING)
            ctx.record_event(EventTypes.VERIFICATION_STARTED, {"condition": success_condition})
            await self._emit_events(ctx, event_recorder)

            verification = None
            if success_condition:
                verification = await verifier.verify(success_condition)
            else:
                from app.engine.verification.verifier import compile_expectation
                live_url = getattr(browser.page, "url", "")
                live_title = await browser.page.title() if browser.page else ""
                live_text = await browser.page.evaluate("() => document.body ? document.body.innerText.slice(0, 500) : ''") if browser.page else ""
                compiled_cond = await compile_expectation(
                    objective,
                    "",
                    page_context={"url": live_url, "title": live_title, "text": live_text},
                )
                if compiled_cond:
                    verification = await verifier.verify(compiled_cond)

            if verification and verification.passed:
                ctx.transition(ExecutionState.COMPLETED)
                ctx.completed_at = datetime.now(timezone.utc)
                ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
                    "completed_at": ctx.completed_at.isoformat(),
                    "verified": True,
                })
                await self._emit_events(ctx, event_recorder)
                return {
                    "success": True,
                    "execution_id": str(execution_id),
                    "state": ExecutionState.COMPLETED.value,
                    "verification": verification.to_dict(),
                    "current_state": ctx.current_state,
                    "events": ctx.events,
                    "observations": ctx.observations,
                }
            else:
                ctx.transition(ExecutionState.UNVERIFIED)
                ctx.completed_at = datetime.now(timezone.utc)
                ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
                    "completed_at": ctx.completed_at.isoformat(),
                    "verification_status": "unverified",
                    "failure_category": "verifier_rejected_agent_completion",
                    "reason": "Agent completed but verifier rejected verification",
                })
                await self._emit_events(ctx, event_recorder)
                return {
                    "success": False,
                    "execution_id": str(execution_id),
                    "state": ExecutionState.UNVERIFIED.value,
                    "failure_category": "verifier_rejected_agent_completion",
                    "verification": verification.to_dict() if verification else {},
                    "error": "Verifier rejected agent completion",
                    "error_code": "UNVERIFIED",
                    "current_state": ctx.current_state,
                    "events": ctx.events,
                    "observations": ctx.observations,
                }

        elif outcome.status == "NEEDS_INPUT":
            ctx.transition(ExecutionState.PAUSED)
            ctx.control_state = "human"
            ctx.record_event(EventTypes.EXECUTION_PAUSED, {
                "reason": outcome.reason,
                "control_state": "human",
            })
            await self._emit_events(ctx, event_recorder)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "state": ExecutionState.PAUSED.value,
                "control_state": "human",
                "error": outcome.reason,
                "current_state": ctx.current_state,
                "events": ctx.events,
                "observations": ctx.observations,
            }

        elif outcome.status == "BLOCKED":
            try:
                ctx.transition(ExecutionState.BLOCKED)
            except Exception:
                ctx.state = ExecutionState.BLOCKED
            ctx.completed_at = datetime.now(timezone.utc)
            fail_cat = getattr(outcome, "failure_category", None) or "agent_blocked"
            ctx.record_event(EventTypes.EXECUTION_FAILED, {
                "error": outcome.reason,
                "error_code": "BLOCKED",
                "failure_category": fail_cat,
                "completed_at": ctx.completed_at.isoformat(),
            })
            await self._emit_events(ctx, event_recorder)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "state": ExecutionState.BLOCKED.value,
                "failure_category": fail_cat,
                "error": outcome.reason,
                "error_code": "BLOCKED",
                "current_state": ctx.current_state,
                "events": ctx.events,
                "observations": ctx.observations,
            }

        elif outcome.status == "UNVERIFIED":
            ctx.transition(ExecutionState.UNVERIFIED)
            ctx.completed_at = datetime.now(timezone.utc)
            fail_cat = getattr(outcome, "failure_category", None) or "agent_outcome_unverified"
            ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
                "completed_at": ctx.completed_at.isoformat(),
                "verification_status": "unverified",
                "failure_category": fail_cat,
                "reason": outcome.reason,
            })
            await self._emit_events(ctx, event_recorder)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "state": ExecutionState.UNVERIFIED.value,
                "failure_category": fail_cat,
                "error": outcome.reason,
                "error_code": "UNVERIFIED",
                "current_state": ctx.current_state,
                "events": ctx.events,
                "observations": ctx.observations,
            }

        else: # FAILED
            if ctx.state not in (ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.BLOCKED, ExecutionState.UNVERIFIED):
                try:
                    ctx.transition(ExecutionState.FAILED)
                except Exception:
                    ctx.state = ExecutionState.FAILED
            ctx.completed_at = datetime.now(timezone.utc)
            fail_cat = getattr(outcome, "failure_category", None) or "agent_loop_failed"
            ctx.record_event(EventTypes.EXECUTION_FAILED, {
                "error": outcome.reason,
                "error_code": "FAILED",
                "failure_category": fail_cat,
                "completed_at": ctx.completed_at.isoformat(),
            })
            await self._emit_events(ctx, event_recorder)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "state": ExecutionState.FAILED.value,
                "failure_category": fail_cat,
                "error": outcome.reason,
                "error_code": "FAILED",
                "current_state": ctx.current_state,
                "events": ctx.events,
                "observations": ctx.observations,
            }

    async def _execute_inner(
        self,
        execution_id: uuid.UUID,
        flow_steps: list[dict] | None = None,
        success_condition: dict | None = None,
        credential_store: CredentialStore | None = None,
        target_url: str = "",
        event_recorder: Callable | None = None,
        preconditions: dict | None = None,
        dependency_plan: list[dict] | None = None,
        objective: str | None = None,
        expected_outcome: str | None = None,
        fail_on_healed: bool | None = None,
        target_flow: Any | None = None,
        flows: list[Any] | None = None,
        persona: str = "default",
        current_state: dict[str, Any] | None = None,
        session_manager: Any | None = None,
        reset_strategy: str = "none",
        project: Any | None = None,
    ) -> dict[str, Any]:
        """Inner execution logic with state-aware planning and prerequisite resolution."""
        from types import SimpleNamespace
        from app.modules.flows.schemas import FlowStateContract, StateAssertion
        from app.modules.flows.dependency_resolver import DependencyResolver, _keys_collide

        if fail_on_healed is None:
            try:
                from app.engine.execution.control import get_execution_fail_on_healed
                fail_on_healed = await get_execution_fail_on_healed(str(execution_id))
            except Exception:
                fail_on_healed = False

        if not success_condition and (objective or expected_outcome):
            from app.engine.verification.verifier import compile_expectation
            success_condition = await compile_expectation(
                objective or "",
                expected_outcome or "",
                page_context={"target_url": target_url},
            )

        target_host = None
        if target_url:
            try:
                from urllib.parse import urlparse
                target_host = (urlparse(target_url).hostname or "").lower()
            except Exception:
                pass

        available_creds = set()
        if credential_store and hasattr(credential_store, "_credentials"):
            available_creds = set(credential_store._credentials.keys())

        ctx = ExecutionContext(
            execution_id=str(execution_id),
            target_url=target_url,
            credentials=credential_store or CredentialStore(),
            persona=persona,
            current_state=dict(current_state or {}),
            session_manager=session_manager,
            app_host=target_host,
            available_credentials=available_creds,
            project=project,
            execution_limits=getattr(project, "execution_limits", None),
            safety_restrictions=getattr(project, "safety_restrictions", None),
            browser_settings=getattr(project, "browser_settings", None),
        )
        if f"authenticated:{persona}" not in ctx.current_state:
            ctx.current_state[f"authenticated:{persona}"] = False
        if "authenticated:False" not in ctx.current_state and not ctx.current_state.get(f"authenticated:{persona}"):
            ctx.current_state["authenticated:False"] = True

        # Step 1: QUEUED
        ctx.transition(ExecutionState.QUEUED)
        ctx.record_event(EventTypes.EXECUTION_QUEUED, {"execution_id": str(execution_id)})
        await self._emit_events(ctx, event_recorder)

        # Step 2: INITIALIZING
        ctx.transition(ExecutionState.INITIALIZING)
        ctx.record_event(EventTypes.EXECUTION_INITIALIZING, {})
        await self._emit_events(ctx, event_recorder)

        # Step 3: PLANNING
        ctx.transition(ExecutionState.PLANNING)

        if target_flow is None:
            target_contract = FlowStateContract(
                reset_strategy=reset_strategy if reset_strategy in ("none", "re_establish", "create_new", "skip_if_exists") else "none",
            )
            if preconditions:
                for k, v in preconditions.items():
                    target_contract.requires.append(StateAssertion(key=str(k), value=v))
            target_flow_obj = SimpleNamespace(
                id=execution_id,
                name="Target Flow",
                steps=flow_steps,
                preconditions=preconditions,
                success_condition=success_condition,
                dependencies=dependency_plan or [],
                provides_capabilities=[],
                state_contract=target_contract,
            )
        else:
            target_flow_obj = target_flow
            target_contract = getattr(target_flow_obj, "state_contract", None)
            if not flow_steps and hasattr(target_flow_obj, "steps") and target_flow_obj.steps:
                flow_steps = list(target_flow_obj.steps)
            if not success_condition and hasattr(target_flow_obj, "success_condition"):
                success_condition = target_flow_obj.success_condition
            if not preconditions and hasattr(target_flow_obj, "preconditions"):
                preconditions = target_flow_obj.preconditions

        all_flows = list(flows) if flows else [target_flow_obj]
        if not any(str(getattr(f, "id", "")) == str(getattr(target_flow_obj, "id", "")) for f in all_flows):
            all_flows.append(target_flow_obj)

        if dependency_plan:
            for dep in dependency_plan:
                if not any(str(getattr(f, "id", "")) == str(dep.get("id")) for f in all_flows):
                    dep_contract = dep.get("state_contract") or FlowStateContract(
                        produces=[StateAssertion(key=str(c), value=True) for c in dep.get("provides_capabilities", [])]
                    )
                    all_flows.append(SimpleNamespace(
                        id=dep.get("id", uuid.uuid4()),
                        name=dep.get("name", "Dependency"),
                        steps=dep.get("steps", []),
                        preconditions=dep.get("preconditions"),
                        success_condition=dep.get("success_condition"),
                        dependencies=dep.get("dependencies", []),
                        provides_capabilities=dep.get("provides_capabilities", []),
                        state_contract=dep_contract,
                    ))

        available_creds = set()
        for cid in ctx.credentials.list_ids():
            c = ctx.credentials.get(cid)
            if c:
                if hasattr(c, "persona") and c.persona:
                    available_creds.add(c.persona)
                if hasattr(c, "email") and c.email:
                    available_creds.add(c.email)
                available_creds.add(cid)

        from app.observability.tracing import async_trace_span
        target_id_str = str(getattr(target_flow_obj, "id", execution_id))
        span_attrs = {
            "flow_id": target_id_str,
            "step_count": len(flow_steps or []),
            "persona": str(persona),
        }

        try:
            async with async_trace_span("plan", span_attrs):
                plan = DependencyResolver.resolve_execution_plan(
                    target=target_flow_obj,
                    flows=all_flows,
                    current_state=ctx.current_state,
                    persona=persona,
                    available_credentials=available_creds,
                )
        except Exception as plan_err:
            logger.warning("Execution planning failed: %s", plan_err)
            ctx.transition(ExecutionState.FAILED)
            ctx.record_event(EventTypes.EXECUTION_FAILED, {"error": str(plan_err)})
            await self._emit_events(ctx, event_recorder)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "error": f"Planning failed: {plan_err}",
                "error_code": "PLANNING_FAILED",
                "state": ExecutionState.FAILED.value,
                "current_state": ctx.current_state,
                "events": ctx.events,
                "observations": ctx.observations,
            }

        ctx.execution_plan = plan

        # If plan.unresolved is non-empty:
        if plan.unresolved:
            ctx.transition(ExecutionState.PREREQUISITE_FAILED)
            plan_payload = {
                "steps": [s.__dict__ if hasattr(s, "__dict__") else str(s) for s in plan.steps],
                "estimated_cost": plan.estimated_cost,
                "unresolved": [u.model_dump() if hasattr(u, "model_dump") else str(u) for u in plan.unresolved],
                "warnings": plan.warnings,
            }
            ctx.record_event(EventTypes.EXECUTION_PLANNED, plan_payload)
            ctx.record_event(EventTypes.PREREQUISITE_FAILED, {
                "unresolved": [u.model_dump() if hasattr(u, "model_dump") else str(u) for u in plan.unresolved],
            })
            await self._emit_events(ctx, event_recorder)
            return {
                "success": False,
                "execution_id": str(execution_id),
                "error": f"Unresolved prerequisites: {', '.join(str(u.key) for u in plan.unresolved)}",
                "error_code": "PREREQUISITE_FAILED",
                "unresolved": [u.key for u in plan.unresolved],
                "current_state": ctx.current_state,
                "state": "UNVERIFIED",
                "events": ctx.events,
                "observations": ctx.observations,
            }

        # Emit EXECUTION_PLANNED event with the plan
        ctx.record_event(EventTypes.EXECUTION_PLANNED, {
            "steps": [s.__dict__ if hasattr(s, "__dict__") else str(s) for s in plan.steps],
            "estimated_cost": plan.estimated_cost,
            "unresolved": [],
            "warnings": plan.warnings,
        })
        await self._emit_events(ctx, event_recorder)

        browser = BrowserSession(browser_settings=ctx.browser_settings)
        exec_id = str(execution_id)
        frame_task: asyncio.Task | None = None
        nav_unbind: Callable[[], None] | None = None
        try:
            # Step 4: Start browser
            await browser.start()
            ctx.transition(ExecutionState.BROWSER_READY)
            ctx.record_event(EventTypes.BROWSER_STARTED, {"browser": "chromium"})
            await self._emit_events(ctx, event_recorder)

            # Hook network errors to execution context
            async def _record_network_error(err_data: dict[str, Any]):
                try:
                    ctx.record_event(EventTypes.NETWORK_ERROR, err_data)
                    await self._emit_events(ctx, event_recorder)
                except Exception as ne_err:
                    logger.debug("Failed to record network error event: %s", ne_err)

            browser.on_network_error = _record_network_error
            verifier = Verifier(browser.page)
            action_executor = ActionExecutor(
                browser.page,
                event_recorder=None,
                credential_store=credential_store,
            )

            # Observe URL/title changes for viewport
            nav_unbind = self._bind_nav_observer(browser, exec_id)
            frame_task = asyncio.create_task(
                self._frame_producer(browser, exec_id)
            )

            # Step 5: Prerequisite resolution
            prereq_steps = [s for s in plan.steps if s.role == "prerequisite"]
            by_id_map = {str(getattr(f, "id", "")): f for f in all_flows}
            for f in all_flows:
                if hasattr(f, "name") and f.name:
                    by_id_map[str(f.name)] = f

            if prereq_steps:
                async with async_trace_span("resolve_prerequisites", span_attrs):
                    ctx.transition(ExecutionState.RESOLVING_PREREQUISITES)
                    from app.modules.flows.auth import Authenticator, SessionManager
                    from app.modules.product_graph.schemas import AuthCapability
                    if not ctx.session_manager:
                        ctx.session_manager = SessionManager()

                    for p_step in prereq_steps:
                        is_auth = (
                            any("auth" in str(getattr(a, "key", "")).lower() or getattr(a, "key", "") in ("authenticated", f"authenticated:{persona}") for a in p_step.establishes)
                            or "auth" in getattr(p_step, "flow_name", "").lower()
                        )
                        if is_auth:
                            cred = None
                            for cid in ctx.credentials.list_ids():
                                c = ctx.credentials.get(cid)
                                if c:
                                    cred = c
                            proj_id = getattr(target_flow_obj, "project_id", None)
                            auth_cap = None
                            if proj_id:
                                try:
                                    from app.infrastructure.database.session import async_session_factory
                                    from app.modules.product_graph.repository import ProductGraphRepository
                                    async with async_session_factory() as db:
                                        repo = ProductGraphRepository(db)
                                        auth_cap = await repo.get_auth_capability_for_persona(proj_id, persona)
                                except Exception as query_err:
                                    logger.debug("Could not load auth capability from graph: %s", query_err)

                            if not auth_cap:
                                auth_cap = AuthCapability(
                                    project_id=proj_id or uuid.uuid4(),
                                    name=p_step.flow_name or "Authenticate",
                                    login_url=target_url or "/login",
                                    persona=persona,
                                )
                            elif target_url and getattr(auth_cap, "login_url", None) and auth_cap.login_url.startswith("/"):
                                from urllib.parse import urljoin
                                auth_cap.login_url = urljoin(target_url, auth_cap.login_url)

                            try:
                                session_state, was_reused = await ctx.session_manager.get_or_establish(
                                    execution_id=exec_id,
                                    persona=persona,
                                    capability=auth_cap,
                                    browser=browser,
                                    credential=cred,
                                    authenticator=Authenticator(),
                                    event_recorder=event_recorder,
                                )
                                ctx.current_state[f"authenticated:{persona}"] = True
                                ctx.current_state["authenticated"] = True
                                ctx.current_state.pop("authenticated:False", None)
                                for a in p_step.establishes:
                                    ctx.current_state[a.key] = a.value
                                ctx.record_event(EventTypes.PREREQUISITE_RESOLVED, {
                                    "flow_id": p_step.flow_id,
                                    "flow_name": p_step.flow_name,
                                    "established_state": dict(ctx.current_state),
                                    "was_reused": was_reused,
                                })
                                await self._emit_events(ctx, event_recorder)
                            except Exception as auth_err:
                                logger.warning("Auth prerequisite resolution failed: %s", auth_err)
                                try:
                                    ctx.transition(ExecutionState.BLOCKED)
                                except Exception:
                                    ctx.state = ExecutionState.BLOCKED
                                ctx.record_event(EventTypes.EXECUTION_FAILED, {
                                    "flow_id": p_step.flow_id,
                                    "error": str(auth_err),
                                    "error_code": "BLOCKED",
                                    "failure_category": "AUTH",
                                })
                                await self._emit_events(ctx, event_recorder)
                                return {
                                    "success": False,
                                    "execution_id": str(execution_id),
                                    "error": f"Prerequisite auth failed: {auth_err}",
                                    "error_code": "BLOCKED",
                                    "failure_category": "AUTH",
                                    "state": ExecutionState.BLOCKED.value,
                                    "current_state": ctx.current_state,
                                    "events": ctx.events,
                                    "observations": ctx.observations,
                                }
                        else:
                            prereq_flow = by_id_map.get(p_step.flow_id)
                            if prereq_flow:
                                prereq_steps_list = getattr(prereq_flow, "steps", []) or []
                                for dep_step in prereq_steps_list:
                                    if await is_cancel_requested(exec_id):
                                        return {
                                            "success": False,
                                            "execution_id": str(execution_id),
                                            "error": "Execution cancelled during prerequisite setup",
                                            "error_code": ErrorCode.CANCELLED,
                                            "state": "CANCELLED",
                                            "current_state": ctx.current_state,
                                            "events": ctx.events,
                                            "observations": ctx.observations,
                                        }
                                    await self._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
                                    await self._execute_step_with_retry(ctx, browser, action_executor, dep_step, ctx.current_step_index, event_recorder)
                                    ctx.current_step_index += 1

                                prereq_contract = getattr(prereq_flow, "state_contract", None)
                                if prereq_contract and hasattr(prereq_contract, "produces"):
                                    for prod in prereq_contract.produces:
                                        ctx.current_state[prod.key] = prod.value
                                for a in p_step.establishes:
                                    ctx.current_state[a.key] = a.value

                                ctx.record_event(EventTypes.PREREQUISITE_RESOLVED, {
                                    "flow_id": p_step.flow_id,
                                    "flow_name": p_step.flow_name,
                                    "established_state": dict(ctx.current_state),
                                })
                                await self._emit_events(ctx, event_recorder)

            # Step 6: Contamination detection
            conflicting_keys = []
            steps_to_check = flow_steps or (getattr(target_flow_obj, "steps", []) or [])
            all_mutated_keys = set()
            if target_contract:
                for m in getattr(target_contract, "mutates", []) + getattr(target_contract, "consumes", []):
                    all_mutated_keys.add(m.key if hasattr(m, "key") else str(m))

            for st in steps_to_check:
                if isinstance(st, dict):
                    for m in st.get("mutates", []) + st.get("consumes", []):
                        m_key = m.get("key") if isinstance(m, dict) else str(m)
                        all_mutated_keys.add(m_key)

            for m_key in all_mutated_keys:
                for curr_key, curr_val in ctx.current_state.items():
                    if curr_val and _keys_collide(m_key, curr_key):
                        conflicting_keys.append(m_key)

            steps_to_skip_indices = set()
            if conflicting_keys:
                ctx.transition(ExecutionState.CONTAMINATION_DETECTED)
                ctx.record_event(EventTypes.STATE_CONTAMINATED, {
                    "conflicting_state_keys": conflicting_keys,
                    "flow_id": str(getattr(target_flow_obj, "id", execution_id)),
                })
                await self._emit_events(ctx, event_recorder)

                r_strategy = getattr(target_contract, "reset_strategy", reset_strategy) or reset_strategy
                action_taken = "none"
                if r_strategy == "re_establish":
                    action_taken = "re_established_prerequisite"
                    for p_step in prereq_steps:
                        prereq_flow = by_id_map.get(p_step.flow_id)
                        if prereq_flow:
                            for dep_step in (getattr(prereq_flow, "steps", []) or []):
                                await self._execute_step_with_retry(ctx, browser, action_executor, dep_step, ctx.current_step_index, event_recorder)
                                ctx.current_step_index += 1
                elif r_strategy == "create_new":
                    action_taken = "created_fresh_entity"
                elif r_strategy == "skip_if_exists":
                    action_taken = "skipped_existing_steps"
                    for idx, st in enumerate(steps_to_check):
                        if isinstance(st, dict):
                            for m in st.get("mutates", []) + st.get("produces", []):
                                m_k = m.get("key") if isinstance(m, dict) else str(m)
                                if any(_keys_collide(m_k, ck) for ck in conflicting_keys):
                                    steps_to_skip_indices.add(idx)
                else:
                    action_taken = "warn_and_proceed"
                    logger.warning("State contamination detected with reset_strategy='none': %s", conflicting_keys)

                ctx.record_event(EventTypes.STATE_RESET, {
                    "reset_strategy": r_strategy,
                    "action_taken": action_taken,
                    "conflicting_keys": conflicting_keys,
                })
                await self._emit_events(ctx, event_recorder)

            # Step 7: RUNNING
            ctx.transition(ExecutionState.RUNNING)
            ctx.started_at = datetime.now(timezone.utc)
            ctx.record_event(EventTypes.EXECUTION_STARTED, {"started_at": ctx.started_at.isoformat()})
            await self._emit_events(ctx, event_recorder)
            await publish_state(exec_id, "executing", browser.page.url, browser.page.url and "")

            # Step 8: Navigate to initial URL
            if target_url:
                await browser.navigate(target_url)
                await publish_state(exec_id, "navigating", target_url, "")
                ss_data = await self._capture_live_snapshot(browser, exec_id, state="navigating")
                page_payload: dict[str, Any] = {"url": target_url, **ss_data}
                ctx.record_event(EventTypes.PAGE_LOADED, page_payload)
                ctx.record_event(EventTypes.BROWSER_SCREENSHOT, ss_data)
                await self._emit_events(ctx, event_recorder)

            # If flow has no pre-baked steps but has an objective, dynamically plan actions or run autonomous agent loop
            effective_obj = objective or (getattr(target_flow, "objective", None) if target_flow else None)
            from app.config.settings import settings
            if settings.AGENT_EXECUTION_ENABLED and effective_obj and not flow_steps:
                return await self._execute_via_agent_loop(
                    ctx=ctx,
                    browser=browser,
                    verifier=verifier,
                    execution_id=execution_id,
                    target_url=target_url,
                    objective=effective_obj,
                    success_condition=success_condition,
                    credential_store=credential_store,
                    event_recorder=event_recorder,
                    persona=persona,
                    project=project,
                )

            if not flow_steps and objective:
                from app.engine.ai.settings import ai_settings
                if ai_settings.ai_enabled:
                    try:
                        from app.engine.ai.provider import get_ai_provider
                        from app.engine.ai.reasoner import AgentReasoner
                        from app.engine.ai.memory import AgentMemory
                        ai_provider = get_ai_provider()
                        if ai_provider:
                            reasoner = AgentReasoner(ai_provider)
                            memory = AgentMemory(execution_id=execution_id, objective=objective)
                            try:
                                interpretation = await reasoner.interpret_goal(objective)
                            except Exception:
                                interpretation = reasoner._heuristic_goal(objective)
                            current_url = getattr(browser.page, "url", "")
                            live_title = await browser.page.title() if browser.page else ""
                            obs = {"url": current_url, "title": live_title, "interactive_elements": []}
                            plan = await reasoner.plan_journey(memory, interpretation, obs, False)
                            if plan and plan.steps:
                                from app.engine.ai.schemas import ActionProposal
                                from app.engine.ai.validator import validate_action_proposal, ProposalRejected

                                validated_steps: list[dict] = []
                                rejected_steps: list[dict] = []
                                for s in plan.steps:
                                    proposal = ActionProposal(
                                        action=s.action,
                                        target=s.target,
                                        value=s.value,
                                        reason=s.description or f"Perform {s.action}",
                                    )
                                    try:
                                        validate_action_proposal(
                                            proposal,
                                            app_host=getattr(ctx, "app_host", None),
                                            available_credentials=getattr(ctx, "available_credentials", set()),
                                        )
                                        validated_steps.append({
                                            "type": s.action,
                                            "target": s.target,
                                            "value": s.value,
                                            "description": s.description,
                                        })
                                    except (ProposalRejected, ValueError) as e:
                                        rejected_steps.append({
                                            "step": {
                                                "action": s.action,
                                                "target": s.target,
                                                "description": s.description,
                                            },
                                            "reason": str(e),
                                        })

                                if rejected_steps:
                                    logger.info("Dynamic planning rejected %d steps: %s", len(rejected_steps), rejected_steps)
                                    ctx.record_event(EventTypes.AI_PROPOSAL_REJECTED, {
                                        "count": len(rejected_steps),
                                        "reasons": rejected_steps,
                                    })

                                if not validated_steps:
                                    # All AI-proposed steps failed validation — fail-closed
                                    ctx.record_event(EventTypes.AI_PROPOSAL_ALL_REJECTED, {
                                        "reason": "All AI-proposed steps failed validation",
                                        "rejected_count": len(rejected_steps),
                                    })
                                    await self._mark_unverified(
                                        ctx, execution_id,
                                        failure_category="ai_proposal_rejected",
                                        error_message="All AI-proposed steps failed validation; cannot execute.",
                                    )
                                    await self._emit_events(ctx, event_recorder)
                                    return {
                                        "success": False,
                                        "execution_id": str(execution_id),
                                        "error": "All AI-proposed steps failed validation; cannot execute.",
                                        "error_code": "UNVERIFIED",
                                        "failure_category": "ai_proposal_rejected",
                                        "state": "UNVERIFIED",
                                        "current_state": ctx.current_state,
                                        "events": ctx.events,
                                        "observations": ctx.observations,
                                    }

                                flow_steps = validated_steps
                                if plan.success_condition and (not success_condition or success_condition == {"url_matches": ".*"}):
                                    success_condition = plan.success_condition
                                logger.info("Planned %d dynamic steps (%d rejected) for objective '%s'", len(flow_steps), len(rejected_steps), objective)
                    except Exception as plan_err:
                        logger.warning("Dynamic journey planning failed: %s", plan_err)

            if not flow_steps:
                ctx.transition(ExecutionState.UNVERIFIED)
                ctx.completed_at = datetime.now(timezone.utc)
                ctx.record_event(EventTypes.EXECUTION_COMPLETED, {
                    "completed_at": ctx.completed_at.isoformat(),
                    "verification_status": "unverified",
                    "failure_category": "no_steps_no_agent",
                    "reason": "Flow has no steps and agent execution is disabled.",
                })
                await self._emit_events(ctx, event_recorder)
                return {
                    "success": False,
                    "execution_id": str(execution_id),
                    "error": "Flow has no steps and agent execution is disabled.",
                    "error_code": "UNVERIFIED",
                    "failure_category": "no_steps_no_agent",
                    "state": ExecutionState.UNVERIFIED.value,
                    "current_state": ctx.current_state,
                    "events": ctx.events,
                    "observations": ctx.observations,
                }

            async with async_trace_span("execute_target", span_attrs):
                for i, step in enumerate(flow_steps):
                    if i in steps_to_skip_indices:
                        logger.info("Skipping step %d due to state contamination skip_if_exists strategy", i)
                        continue

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
                            "current_state": ctx.current_state,
                            "events": ctx.events,
                            "observations": ctx.observations,
                            "state": "CANCELLED",
                        }

                    # Pause gate before each step — drain input while paused
                    await self._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
                    ctx.current_step_index = i
                    browser.current_step_index = i
                    await publish_state(exec_id, "executing", browser.page.url, "")
                    try:
                        await self._capture_live_snapshot(browser, exec_id, step_index=i, state="observing")
                    except Exception:
                        pass
                    await self._execute_step_with_retry(ctx, browser, action_executor, step, i, event_recorder)

                    # Step-level auth barrier gate: heal immediately if redirected to an auth barrier
                    from app.engine.browser.auth import is_auth_url, is_auth_page
                    current_p_url = getattr(browser.page, "url", "")
                    step_target_url = self._extract_step_target_url(step, base_url=ctx.target_url or current_p_url)
                    # Only trigger if the step was aiming for a non-auth destination but got redirected to an auth page
                    step_was_redirected_to_auth = (
                        bool(step_target_url)
                        and not is_auth_url(step_target_url)
                        and (is_auth_url(current_p_url) or await is_auth_page(browser.page, current_p_url))
                    )
                    if step_was_redirected_to_auth:
                        healed = await self._heal_auth_barrier(ctx, browser, current_p_url, step_target_url or ctx.target_url or current_p_url, event_recorder)
                        dest_to_nav = step_target_url or ctx.target_url
                        if healed and dest_to_nav and not is_auth_url(browser.page.url):
                            try:
                                logger.info("Navigating to destination after step auth barrier healing: %s", dest_to_nav)
                                await browser.navigate(dest_to_nav)
                                await asyncio.sleep(1.0)
                            except Exception as re_nav_err:
                                logger.debug("Re-navigation after auth barrier healing failed: %s", re_nav_err)

                    step_check = await self._verify_step_postcondition(ctx, browser, verifier, step, i, event_recorder)
                    if step_check is not None and not step_check.passed:
                        failed_checks = [check for check in step_check.checks if not check.passed]
                        unverified_types = {"no_condition", "empty_condition", "unknown_condition", "malformed_condition", "vacuous_condition"}
                        error_code = "UNVERIFIED" if failed_checks and all(check.type in unverified_types for check in failed_checks) else ErrorCode.VERIFICATION_FAILED
                        raise ExecutionError(f"Step {step.get('step_id', i)} postcondition failed", error_code=error_code)

                    # Update context.current_state after each step based on produces / mutates
                    if isinstance(step, dict):
                        for p in step.get("produces", []):
                            k = p.get("key") if isinstance(p, dict) else str(p)
                            v = p.get("value", True) if isinstance(p, dict) else True
                            ctx.current_state[k] = v
                        for m in step.get("mutates", []):
                            k = m.get("key") if isinstance(m, dict) else str(m)
                            v = m.get("value", True) if isinstance(m, dict) else True
                            ctx.current_state[k] = v

                    # Drain any human input queued mid-step
                    await self._process_user_input(browser, exec_id)
                    # Pause gate after step
                    await self._check_and_handle_pause(ctx, browser, exec_id, event_recorder)
                    try:
                        await self._capture_live_snapshot(browser, exec_id, step_index=i, state="executing")
                    except Exception:
                        pass

            # Update context.current_state with target flow produces contract
            if target_contract and hasattr(target_contract, "produces"):
                for prod in target_contract.produces:
                    ctx.current_state[prod.key] = prod.value

            # Step 9: Verify final success condition
            ctx.transition(ExecutionState.VERIFYING)
            ctx.record_event(EventTypes.VERIFICATION_STARTED, {"condition": success_condition})
            await self._emit_events(ctx, event_recorder)

            if not success_condition and (objective or expected_outcome) and browser.page:
                try:
                    from app.engine.verification.verifier import compile_expectation
                    live_url = getattr(browser.page, "url", "")
                    live_title = await browser.page.title() if browser.page else ""
                    live_text = await browser.page.evaluate("() => document.body ? document.body.innerText.slice(0, 500) : ''")
                    success_condition = await compile_expectation(
                        objective or "",
                        expected_outcome or "",
                        page_context={"url": live_url, "title": live_title, "text": live_text},
                    )
                except Exception as ex:
                    logger.debug("Live compile expectation failed: %s", ex)

            async with async_trace_span("verify", span_attrs):
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

            # --- AI / Self-Healing Auth Barrier Gate ---
            detected_expected_dest = None
            if not verification.passed:
                from app.engine.browser.auth import is_auth_url, is_auth_page, perform_login

                current_page_url = getattr(browser.page, "url", "")
                failed_checks = [c for c in verification.checks if not c.passed]

                # Invoke AI Reasoner if LLM provider is active
                from app.engine.ai.settings import ai_settings
                ai_recovery_reason = ""
                if ai_settings.ai_enabled:
                    try:
                        from app.engine.ai.provider import get_ai_provider
                        from app.engine.ai.reasoner import AgentReasoner
                        from app.engine.ai.memory import AgentMemory
                        ai_provider = get_ai_provider()
                        if ai_provider:
                            reasoner = AgentReasoner(provider=ai_provider)
                            memory = AgentMemory(
                                execution_id=str(execution_id),
                                objective=objective or "Verify user journey",
                            )
                            current_obs = await browser.observe()
                            recovery_prop = await reasoner.propose_recovery(
                                memory=memory,
                                failure=f"Verification failed on {current_page_url}",
                                failure_code="VERIFICATION_FAILED",
                                observation=current_obs,
                            )
                            if recovery_prop:
                                ai_recovery_reason = recovery_prop.reason
                                logger.info("AI Reasoner proposal: %s (%s)", recovery_prop.strategy, recovery_prop.reason)
                                ctx.record_event("ai_reasoning", {
                                    "strategy": recovery_prop.strategy,
                                    "reason": recovery_prop.reason,
                                    "current_url": current_page_url,
                                })
                                await self._emit_events(ctx, event_recorder)
                    except Exception as ai_err:
                        logger.warning("AI Reasoner call failed: %s", ai_err)

                auth_detected = False
                for c in failed_checks:
                    act = getattr(c, "actual", None)
                    exp = getattr(c, "expected", None)
                    if (act and is_auth_url(str(act))) or is_auth_url(current_page_url):
                        auth_detected = True
                        if exp:
                            detected_expected_dest = str(exp)
                        break

                if not auth_detected and await is_auth_page(browser.page, current_page_url):
                    auth_detected = True

                if auth_detected:
                    healed = await self._heal_auth_barrier(
                        ctx, browser, current_page_url, detected_expected_dest or target_url, event_recorder
                    )
                    if healed:
                        from urllib.parse import urljoin
                        re_target = detected_expected_dest or target_url
                        if re_target and re_target.startswith("/"):
                            re_target = urljoin(current_page_url, re_target)

                        if re_target and browser.page.url != re_target:
                            logger.info("Login succeeded, navigating to target destination: %s", re_target)
                            await browser.navigate(re_target)
                            await asyncio.sleep(1.0)

                        # Re-verify success condition after authenticating
                        re_verification = await verifier.verify(success_condition)
                        if re_verification.passed:
                            logger.info("Verification passed after AI authentication healing!")
                            verification = re_verification

            if verification.passed:
                ctx.record_event(EventTypes.VERIFICATION_PASSED, verification.to_dict())
            else:
                ctx.record_event(EventTypes.VERIFICATION_FAILED, verification.to_dict())
            await self._emit_events(ctx, event_recorder)

            if not verification.passed:
                # Determine appropriate status based on failure reason
                failed_checks = [c for c in verification.checks if not c.passed]
                error_messages = []
                for c in failed_checks:
                    exp_val = getattr(c, "expected", None)
                    act_val = getattr(c, "actual", None)
                    if exp_val is not None or act_val is not None:
                        detail = f"{c.message} (expected: {exp_val!r}, got: {act_val!r})"
                    else:
                        detail = c.message
                    error_messages.append(f"{c.type}: {detail}")
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

                # Check if we're stuck on an auth page or encountered an auth barrier
                from app.engine.browser.auth import is_auth_url, is_auth_page
                current_p_url = getattr(browser.page, "url", "")
                is_auth_blocked = (
                    any("still on auth" in msg.lower() or "url_changed_from" in c.type for c, msg in zip(failed_checks, error_messages))
                    or is_auth_url(current_p_url)
                    or any(c.actual and is_auth_url(str(c.actual)) for c in failed_checks)
                    or await is_auth_page(browser.page, current_p_url)
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
                        "current_state": ctx.current_state,
                        "events": ctx.events,
                        "observations": ctx.observations,
                        "verification": verification.to_dict(),
                        "state": ExecutionState.COMPLETED.value,
                    }
                elif is_auth_blocked:
                    try:
                        ctx.transition(ExecutionState.BLOCKED)
                    except Exception:
                        ctx.state = ExecutionState.BLOCKED
                    dest_info = detected_expected_dest or target_url or "target page"
                    auth_err_msg = (
                        f"Authentication required: Target page '{dest_info}' is protected behind an auth barrier "
                        f"(redirected to '{current_p_url}'). "
                    )
                    if ai_recovery_reason:
                        auth_err_msg += f"AI Analysis: {ai_recovery_reason}. "
                    if not any(ctx.credentials.list_ids()):
                        auth_err_msg += "No test credentials configured in project. Please add a test account in Project Credentials so Kova can authenticate."
                    else:
                        auth_err_msg += f"Verification failed: {error_str}"

                    ctx.completed_at = datetime.now(timezone.utc)
                    ctx.record_event(EventTypes.EXECUTION_FAILED, {
                        "error": auth_err_msg,
                        "error_code": "BLOCKED",
                        "failure_category": "AUTH",
                        "completed_at": ctx.completed_at.isoformat(),
                    })
                    await self._emit_events(ctx, event_recorder)
                    return {
                        "success": False,
                        "execution_id": str(execution_id),
                        "error": auth_err_msg,
                        "error_code": "BLOCKED",
                        "failure_category": "AUTH",
                        "state": ExecutionState.BLOCKED.value,
                        "current_state": ctx.current_state,
                        "events": ctx.events,
                        "observations": ctx.observations,
                    }
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
            evidence_persisted = await self._capture_evidence(ctx, browser, verification, event_recorder)
            if not evidence_persisted:
                raise ExecutionError("Verified result could not be persisted with evidence", error_code="EVIDENCE_PERSISTENCE_FAILED")

            # Enforce gate on 5xx or failed requests after submit/click steps
            click_or_submit_indices = {
                idx for idx, st in enumerate(flow_steps)
                if str(st.get("type", "")).lower() in ("click", "submit")
            }
            if click_or_submit_indices:
                first_submit_idx = min(click_or_submit_indices)
                post_submit_errors = [
                    err for err in getattr(browser, "network_errors", [])
                    if err.get("step_index", 0) >= first_submit_idx
                    and (err.get("status", 0) >= 500 or err.get("type") == "request_failed")
                ]
                if post_submit_errors:
                    err = post_submit_errors[0]
                    method = err.get("method", "POST")
                    path = err.get("path") or urlparse(err.get("url", "")).path or "/"
                    if err.get("status", 0) >= 500:
                        net_err_msg = f"UI reported success but request {method} {path} returned {err.get('status')}"
                    else:
                        net_err_msg = f"UI reported success but request {method} {path} failed: {err.get('failure', 'request failed')}"

                    from app.config.settings import settings
                    if settings.FAIL_ON_NETWORK_ERRORS:
                        logger.warning("Failing execution due to post-action network error: %s", net_err_msg)
                        raise ExecutionError(
                            net_err_msg,
                            error_code=ErrorCode.VERIFICATION_FAILED,
                        )
                    else:
                        logger.warning("Warning: %s (FAIL_ON_NETWORK_ERRORS is false)", net_err_msg)

            # Honest healing gate: if fail_on_healed is requested, reject runs that required AI healing
            ai_assisted_events = [e for e in ctx.events if e.get("type") in ("ai_assisted", EventTypes.AI_ASSISTED)]
            if fail_on_healed and ai_assisted_events:
                raise ExecutionError(
                    f"Execution passed with AI healing on {len(ai_assisted_events)} step(s), but fail_on_healed was requested",
                    error_code="HEALED_EXECUTION_REJECTED",
                )

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
                "state": ExecutionState.COMPLETED.value,
                "current_state": ctx.current_state,
                "events": ctx.events,
                "observations": ctx.observations,
                "verification": verification.to_dict(),
                "final_url": browser.page.url,
                "final_title": await browser.page.title(),
                "duration_ms": int((ctx.completed_at - ctx.started_at).total_seconds() * 1000),
                "ai_healed_steps": len(ai_assisted_events),
            }

        except Exception as e:
            # Step 9: FAILED - always transition to terminal state
            if ctx.state not in (ExecutionState.COMPLETED, ExecutionState.FAILED, ExecutionState.BLOCKED, ExecutionState.UNVERIFIED):
                try:
                    ctx.transition(ExecutionState.FAILED)
                except Exception as transition_err:
                    logger.warning("State transition to FAILED failed: %s", transition_err)
                    ctx.state = ExecutionState.FAILED

            if ctx.state == ExecutionState.BLOCKED:
                try:
                    from app.infrastructure.database.session import async_session_factory
                    from app.modules.executions.models import ExecutionStatus
                    from app.modules.executions.repository import ExecutionRepository

                    async with async_session_factory() as db:
                        repo = ExecutionRepository(db)
                        await repo.update_status(uuid.UUID(str(execution_id)), ExecutionStatus.BLOCKED)
                        await db.commit()
                except Exception as db_err:
                    logger.debug("Failed to persist BLOCKED status for execution %s: %s", execution_id, db_err)

            ctx.completed_at = datetime.now(timezone.utc)
            ctx.record_error(str(e))
            error_code = getattr(e, "error_code", ErrorCode.UNKNOWN)
            ctx.record_event(EventTypes.EXECUTION_FAILED, {
                "error": str(e),
                "error_code": error_code,
                "step": ctx.current_step_index,
                "step_id": ctx.current_step_id,
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
                "current_state": ctx.current_state,
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

            # Upload video and/or trace if captured, and link to execution evidence
            video_url = None
            trace_url = None
            try:
                import os
                if getattr(browser, "video_path", None) and os.path.exists(browser.video_path):
                    from app.engine.browser.evidence_storage import evidence_storage
                    video_url = evidence_storage.upload_file(
                        execution_id=exec_id,
                        file_path=browser.video_path,
                        content_type="video/webm",
                        purpose="execution_video",
                    )
            except Exception as vid_err:
                logger.warning("Failed to upload execution video: %s", vid_err)

            try:
                import os
                if getattr(browser, "trace_path", None) and os.path.exists(browser.trace_path):
                    from app.engine.browser.evidence_storage import evidence_storage
                    trace_url = evidence_storage.upload_file(
                        execution_id=exec_id,
                        file_path=browser.trace_path,
                        content_type="application/zip",
                        purpose="execution_trace",
                    )
            except Exception as tr_err:
                logger.warning("Failed to upload execution trace: %s", tr_err)

            if (video_url or trace_url) and event_recorder is not None:
                try:
                    from app.infrastructure.database.session import async_session_factory
                    from app.modules.executions.evidence_service import EvidenceService

                    async with async_session_factory() as db:
                        await EvidenceService(db).attach_execution_artifacts(
                            execution_id=execution_id,
                            video_url=video_url,
                            trace_url=trace_url,
                        )
                        await db.commit()
                except Exception as art_err:
                    logger.warning("Failed to attach video/trace artifacts: %s", art_err)

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
                try:
                    ctrl = await get_control_state(execution_id)
                    if ctrl in ("human", "paused"):
                        state = "paused"
                except Exception as ctrl_err:
                    logger.debug("Control state read failed (graceful degradation): %s", ctrl_err)
                ss_bytes = await page.screenshot(type="jpeg", quality=45, timeout=2000)
                if ss_bytes:
                    try:
                        await publish_frame(execution_id, ss_bytes, state)
                    except Exception as frame_err:
                        logger.debug("Frame broadcast failed (graceful degradation): %s", frame_err)
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
    async def _heal_auth_barrier(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        current_page_url: str,
        expected_destination: str | None,
        event_recorder: Callable | None,
    ) -> bool:
        """Authenticate against an auth barrier using available test credentials or on-the-fly registration."""
        from app.engine.browser.auth import perform_login, is_auth_url, is_auth_page
        import secrets

        # Collect distinct credentials
        available_creds = []
        seen_cred_keys = set()
        for cid in ctx.credentials.list_ids():
            c = ctx.credentials.get(cid)
            if c and c.email and c.get_password():
                ckey = (c.email.strip().lower(), c.get_password())
                if ckey not in seen_cred_keys:
                    seen_cred_keys.add(ckey)
                    available_creds.append(c)

        for cred_to_use in available_creds:
            logger.info(
                "Auth barrier detected on %s (expected %s). Attempting AI self-healing authentication as %s",
                current_page_url, expected_destination, cred_to_use.email,
            )
            ctx.record_event(EventTypes.RECOVERY_STARTED, {
                "strategy": "auth_barrier_healing",
                "message": f"Target page requires authentication (redirected to {current_page_url}). Logging in using project credentials.",
                "email": cred_to_use.email,
                "expected_destination": expected_destination or ctx.target_url,
            })
            await self._emit_events(ctx, event_recorder)

            login_ok, login_msg = await perform_login(
                browser.page,
                email=cred_to_use.email,
                password=cred_to_use.get_password(),
            )

            if login_ok:
                logger.info("Authentication succeeded as %s", cred_to_use.email)
                ctx.record_event(EventTypes.AI_ASSISTED, {
                    "healing_type": "auth_barrier_healed",
                    "original_auth_url": current_page_url,
                    "destination": browser.page.url,
                    "authenticated_as": cred_to_use.email,
                    "message": f"Detected auth wall on {expected_destination or 'target'}. Authenticated with test credentials.",
                })
                await self._emit_events(ctx, event_recorder)
                return True
            else:
                logger.info("Login as %s did not succeed: %s. Trying subsequent credentials if available.", cred_to_use.email, login_msg)

        # On-the-fly registration fallback if all existing credentials failed or none configured
        try:
            logger.info("Attempting automatic test account registration fallback on %s", current_page_url)
            random_suffix = secrets.token_hex(4)
            auto_email = f"kova-tester-{random_suffix}@example.com"
            auto_pass = f"KovaPass!{random_suffix}"

            ctx.record_event(EventTypes.RECOVERY_STARTED, {
                "strategy": "auth_auto_registration",
                "message": f"Attempting on-the-fly test account registration on {current_page_url}.",
                "email": auto_email,
                "expected_destination": expected_destination or ctx.target_url,
            })
            await self._emit_events(ctx, event_recorder)

            signup_ok, signup_msg = await perform_login(
                browser.page,
                email=auto_email,
                password=auto_pass,
                name="Kova Tester",
                is_signup=True,
            )
            if signup_ok:
                logger.info("On-the-fly test account registration succeeded as %s", auto_email)
                from app.engine.credentials.models import Credential as EngineCredential
                ctx.credentials.add(EngineCredential(id=f"auto-{random_suffix}", email=auto_email, password=auto_pass))
                ctx.credentials.add(EngineCredential(id="default", email=auto_email, password=auto_pass))
                ctx.credentials.add(EngineCredential(id="login", email=auto_email, password=auto_pass))

                # Persist to project credentials table if DB is accessible
                try:
                    from app.infrastructure.database.session import async_session_factory
                    from app.modules.executions.repository import ExecutionRepository
                    from app.modules.flows.repository import FlowRepository
                    from app.modules.credentials.repository import CredentialRepository
                    import uuid
                    async with async_session_factory() as cred_db:
                        exec_repo = ExecutionRepository(cred_db)
                        exec_row = await exec_repo.get_by_id(uuid.UUID(ctx.execution_id))
                        if exec_row and exec_row.flow_id:
                            flow_repo = FlowRepository(cred_db)
                            flow_row = await flow_repo.get_by_id(exec_row.flow_id)
                            if flow_row and flow_row.project_id:
                                cred_repo = CredentialRepository(cred_db)
                                await cred_repo.create(
                                    project_id=flow_row.project_id,
                                    name=f"auto-healed-{random_suffix}",
                                    email=auto_email,
                                    password=auto_pass,
                                )
                                await cred_db.commit()
                except Exception as db_save_err:
                    logger.debug("Could not persist auto-healed credential to project: %s", db_save_err)

                ctx.record_event(EventTypes.AI_ASSISTED, {
                    "healing_type": "auth_account_created",
                    "original_auth_url": current_page_url,
                    "destination": browser.page.url,
                    "authenticated_as": auto_email,
                    "message": "Created new test account on the fly to bypass auth wall.",
                })

                await self._emit_events(ctx, event_recorder)
                return True
        except Exception as reg_err:
            logger.debug("On-the-fly registration attempt failed: %s", reg_err)

        return False

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
                try:
                    await publish_frame(execution_id, ss_bytes, state)
                except Exception as frame_err:
                    logger.debug("Live frame publish failed (graceful degradation): %s", frame_err)
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
        purpose: str = "step_evidence",
        step_id: str | None = None,
    ) -> dict[str, Any]:
        """Capture and persist an evidence screenshot (separate from live frames)."""
        eff_step_id = step_id or getattr(ctx, "current_step_id", None) or f"step_{ctx.current_step_index}"
        snapshot_payload: dict[str, Any] = {
            "url": browser.page.url,
            "purpose": purpose,
            "step_id": eff_step_id,
        }
        try:
            ss_bytes = await browser.page.screenshot(type="jpeg", quality=70)
            if ss_bytes:
                storage_res = screenshot_storage.upload_execution_screenshot(
                    execution_id=execution_id,
                    screenshot_bytes=ss_bytes,
                    url=browser.page.url,
                    content_type="image/jpeg",
                    purpose=purpose,
                    step_id=eff_step_id,
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
            if not hasattr(self, "_last_mouse_up"):
                self._last_mouse_up = {}
            for msg in pending:
                kind = msg.get("kind", "")
                try:
                    if kind == "mouse_down":
                        x, y = msg.get("x"), msg.get("y")
                        if x is not None and y is not None:
                            await browser.page.mouse.move(x, y)
                        await browser.page.mouse.down(button="left" if msg.get("button", 0) == 0 else "right")
                    elif kind == "mouse_up":
                        x, y = msg.get("x"), msg.get("y")
                        if x is not None and y is not None:
                            await browser.page.mouse.move(x, y)
                        self._last_mouse_up[execution_id] = (time.monotonic(), x or 0, y or 0)
                        await browser.page.mouse.up(button="left" if msg.get("button", 0) == 0 else "right")
                    elif kind == "click":
                        x, y = msg.get("x", 0), msg.get("y", 0)
                        last_up = self._last_mouse_up.get(execution_id)
                        if last_up is not None:
                            last_time, last_x, last_y = last_up
                            if (time.monotonic() - last_time) <= 0.100 and (abs(x - last_x) <= 20 and abs(y - last_y) <= 20):
                                logger.debug("Ignoring redundant click arriving within 100ms of mouse_up (%d, %d)", x, y)
                                continue
                        await browser.page.mouse.click(x, y)
                    elif kind == "mouse_move":
                        x, y = msg.get("x", 0), msg.get("y", 0)
                        await browser.page.mouse.move(x, y)
                    elif kind == "scroll":
                        dx, dy = msg.get("delta_x", 0), msg.get("delta_y", 0)
                        await browser.page.mouse.wheel(dx, dy)
                    elif kind == "key_down":
                        key = msg.get("key", "")
                        if key and (len(key) == 1 or key in ALLOWED_NAMED_KEYS):
                            await browser.page.keyboard.down(key)
                    elif kind == "key_up":
                        key = msg.get("key", "")
                        if key and (len(key) == 1 or key in ALLOWED_NAMED_KEYS):
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
    _NON_RETRYABLE_ACTION_TEXT = (
        "delete", "remove", "destroy", "purge", "drop",
        "confirm", "pay", "checkout", "purchase", "place order", "submit payment",
    )
    DESTRUCTIVE_ACTION_TEXT = _NON_RETRYABLE_ACTION_TEXT

    async def _verify_step_postcondition(
        self,
        ctx: ExecutionContext,
        browser: BrowserSession,
        verifier: Verifier,
        step: dict,
        step_index: int,
        event_recorder: Callable | None,
    ):
        condition = step.get("postcondition") if isinstance(step, dict) else None
        if not condition:
            return None
        result = await verifier.verify(condition)
        event_payload = {
            "kind": "step_postcondition", "step": step_index,
            "step_id": step.get("step_id"), "expected": condition,
            **result.to_dict(),
        }
        ctx.record_event(EventTypes.VERIFICATION_PASSED if result.passed else EventTypes.VERIFICATION_FAILED, event_payload)
        await self._emit_events(ctx, event_recorder)

        if event_recorder is not None:
            try:
                from app.infrastructure.database.session import async_session_factory
                from app.modules.executions.evidence_service import EvidenceService

                dom_snap = await browser.get_dom_snapshot() if hasattr(browser, "get_dom_snapshot") else ""
                check_msgs = [c.message for c in result.checks if c.message]
                note_str = f"Verification {'passed' if result.passed else 'failed'}: {'; '.join(check_msgs) if check_msgs else 'Checked state'}"

                async with async_session_factory() as db:
                    evidence = await EvidenceService(db).create_verification_evidence(
                        execution_id=uuid.UUID(ctx.execution_id),
                        title=f"Step {step.get('step_id', step_index)} verification",
                        description="Step postcondition passed" if result.passed else "Step postcondition failed",
                        checks=[check.to_dict() for check in result.checks],
                        extra_data={"step_id": step.get("step_id"), "step_index": step_index, "expected": condition},
                        dom_snapshot=dom_snap or None,
                        note=note_str,
                    )
                    if evidence is None:
                        raise RuntimeError("verification evidence was not persisted")
                    await db.commit()
            except Exception as exc:
                raise ExecutionError(
                    f"Could not persist evidence for step {step.get('step_id', step_index)}",
                    error_code="EVIDENCE_PERSISTENCE_FAILED",
                ) from exc
        return result

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
                    "step_id": step.get("step_id") if isinstance(step, dict) else None,
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
            "step_id": step.get("step_id") if isinstance(step, dict) else None,
            "observation": observation,
        })
        await self._emit_events(ctx, event_recorder)

        # Map old/string format to new format if needed
        raw_action = self._normalize_step(step, target_url=ctx.target_url)
        action_type = raw_action.get("type", "")

        # Enforce safety restrictions
        safety = getattr(ctx, "safety_restrictions", None)
        if safety:
            prod_allowed = safety.get("production_access_allowed") if isinstance(safety, dict) else getattr(safety, "production_access_allowed", False)
            forbidden_routes = safety.get("forbidden_routes") if isinstance(safety, dict) else (getattr(safety, "forbidden_routes", []) or [])
            if action_type == "navigate":
                dest_url = raw_action.get("value") or raw_action.get("url") or ctx.target_url or ""
                dest_lower = dest_url.lower()
                if not prod_allowed and ("prod." in dest_lower or "production." in dest_lower or "/prod" in dest_lower):
                    raise ExecutionError("Production access not allowed for this project", error_code="PRODUCTION_ACCESS_DENIED")
                for fr in forbidden_routes:
                    if fr and (fr == dest_url or fr in dest_url):
                        raise ExecutionError(f"Route {dest_url} is forbidden for this project", error_code="FORBIDDEN_ROUTE")

        # Destructive action allowlist check
        if action_type in {"click", "submit", "upload"}:
            from app.engine.safety.destructive_guard import DestructiveActionGuard, DestructiveActionBlocked
            target_val = raw_action.get("target")
            target_css = target_val.get("css") if isinstance(target_val, dict) else (target_val if isinstance(target_val, str) else None)
            target_lbl = step.get("label") or step.get("description") or (target_val.get("text") if isinstance(target_val, dict) else None)
            guard = DestructiveActionGuard(safety)
            try:
                guard.check(
                    action_type=action_type,
                    target_label=target_lbl,
                    target_selector=target_css,
                )
            except DestructiveActionBlocked as e:
                ctx.record_event(EventTypes.DESTRUCTIVE_ACTION_BLOCKED, {
                    "action_type": action_type,
                    "target_label": e.action_label,
                    "reason": e.reason,
                })
                await self._emit_events(ctx, event_recorder)
                try:
                    ctx.transition(ExecutionState.BLOCKED)
                except Exception:
                    ctx.state = ExecutionState.BLOCKED
                raise ExecutionError(str(e), error_code="DESTRUCTIVE_ACTION_BLOCKED")

        ctx.current_step_id = step.get("step_id") if isinstance(step, dict) else None
        action_started_at = datetime.now(timezone.utc)
        action_started_clock = time.monotonic()
        ctx.record_event(EventTypes.ACTION_STARTED, {
            "step": step_index,
            "step_id": ctx.current_step_id,
            "type": action_type,
            "target": raw_action.get("target"),
            "expected_outcome": (step.get("expected_outcome") or step.get("postcondition")) if isinstance(step, dict) else None,
            "started_at": action_started_at.isoformat(),
        })
        await self._emit_events(ctx, event_recorder)

        # Evidence pipeline: capture DOM before action and start step network capture
        dom_before = ""
        try:
            if hasattr(browser, "get_dom_snapshot"):
                dom_before = await browser.get_dom_snapshot()
        except Exception:
            pass
        if hasattr(browser, "start_step_network_capture"):
            browser.start_step_network_capture()

        result = await action_executor.execute(
            raw_action,
            execution_id=uuid.UUID(ctx.execution_id) if ctx.execution_id else None,
        )

        if not result["success"]:
            error_type = result.get("error", {}).get("type", "action_failed")
            error_code = _map_error_code(error_type)

            # At the point where a step fails target resolution, call AgentExecutor only if ai_settings.ai_enabled
            if error_code == ErrorCode.TARGET_NOT_FOUND:
                from app.engine.ai.settings import ai_settings
                if ai_settings.ai_enabled:
                    try:
                        from app.engine.ai.executor import AgentExecutor
                        from app.engine.ai.provider import get_ai_provider
                        from app.engine.ai.reasoner import AgentReasoner
                        from app.engine.ai.validator import validate_action

                        ai_provider = get_ai_provider()
                        if ai_provider:
                            agent_executor = AgentExecutor(
                                execution_id=uuid.UUID(ctx.execution_id) if ctx.execution_id else uuid.uuid4(),
                                reasoner=AgentReasoner(provider=ai_provider),
                                email_provider=None,
                                credential_store=action_executor._credential_store,
                            )
                            alt_target = await agent_executor.heal_target(
                                browser=browser,
                                step=raw_action,
                                error_message=result.get("error", {}).get("message", "Target not found"),
                                observation=observation,
                            )
                            if alt_target:
                                candidate_action = dict(raw_action)
                                candidate_action["target"] = alt_target
                                if validate_action(candidate_action):
                                    logger.info(
                                        "AI proposed alternate target for step %d: %s",
                                        step_index,
                                        alt_target,
                                    )
                                    ctx.record_event(EventTypes.AI_PROPOSAL, {
                                        "stage": "target_healing",
                                        "step": step_index,
                                        "original_target": raw_action.get("target"),
                                        "proposed_target": alt_target,
                                        "action": raw_action.get("type"),
                                        "accepted": True,
                                    })
                                    ctx.record_event(EventTypes.AI_ASSISTED, {
                                        "step": step_index,
                                        "original_target": raw_action.get("target"),
                                        "alternate_target": alt_target,
                                        "action": raw_action.get("type"),
                                    })
                                    await self._emit_events(ctx, event_recorder)

                                    retry_result = await action_executor.execute(
                                        candidate_action,
                                        execution_id=uuid.UUID(ctx.execution_id) if ctx.execution_id else None,
                                    )
                                    if retry_result.get("success"):
                                        result = retry_result
                                        raw_action = candidate_action
                                        action_type = raw_action.get("type", "")
                    except Exception as ai_err:
                        logger.warning("AI target healing failed: %s", ai_err)

            if not result["success"]:
                # Check if the failure happened because the browser was redirected to an auth barrier
                from app.engine.browser.auth import is_auth_url, is_auth_page, perform_login
                current_p_url = getattr(browser.page, "url", "")
                if is_auth_url(current_p_url) or await is_auth_page(browser.page, current_p_url):
                    cred_to_use = None
                    for cid in ctx.credentials.list_ids():
                        c = ctx.credentials.get(cid)
                        if c and c.email and c.get_password():
                            cred_to_use = c
                            break
                    if cred_to_use:
                        logger.info(
                            "Step %d on %s failed due to auth wall. Attempting AI self-healing login as %s",
                            step_index, current_p_url, cred_to_use.email,
                        )
                        ctx.record_event(EventTypes.RECOVERY_STARTED, {
                            "step": step_index,
                            "strategy": "auth_barrier_healing",
                            "message": f"Action blocked by auth redirect ({current_p_url}). Logging in using project credentials.",
                            "email": cred_to_use.email,
                        })
                        await self._emit_events(ctx, event_recorder)

                        login_ok, _ = await perform_login(
                            browser.page,
                            email=cred_to_use.email,
                            password=cred_to_use.get_password(),
                        )
                        if login_ok:
                            if raw_action.get("type") == "navigate" and raw_action.get("url"):
                                await browser.navigate(raw_action["url"])
                            elif ctx.target_url:
                                await browser.navigate(ctx.target_url)
                            await asyncio.sleep(1.0)

                            retry_res = await action_executor.execute(
                                raw_action,
                                execution_id=uuid.UUID(ctx.execution_id) if ctx.execution_id else None,
                            )
                            if retry_res.get("success"):
                                result = retry_res
                                ctx.record_event(EventTypes.AI_ASSISTED, {
                                    "step": step_index,
                                    "healing_type": "auth_barrier_healed",
                                    "message": f"Authenticated as {cred_to_use.email} and successfully retried action.",
                                })
                                await self._emit_events(ctx, event_recorder)


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

        action_completed_payload: dict[str, Any] = {
            "step": step_index,
            "step_id": ctx.current_step_id,
            "type": action_type,
            "result": result.get("result"),
            "url": browser.page.url,
            "started_at": action_started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": max(0, int((time.monotonic() - action_started_clock) * 1000)),
        }

        ctx.record_event(EventTypes.ACTION_COMPLETED, action_completed_payload)
        await self._emit_events(ctx, event_recorder)

        # Evidence pipeline: capture DOM after, a11y tree, network logs, and screenshot
        dom_after = ""
        try:
            if hasattr(browser, "get_dom_snapshot"):
                dom_after = await browser.get_dom_snapshot()
        except Exception:
            pass

        a11y_tree = None
        try:
            if hasattr(browser, "get_a11y_tree"):
                a11y_tree = await browser.get_a11y_tree()
        except Exception:
            pass

        step_network = []
        if hasattr(browser, "stop_step_network_capture"):
            step_network = browser.stop_step_network_capture()

        # Format target locator string
        raw_target = raw_action.get("target")
        locator_str = None
        if isinstance(raw_target, dict):
            locator_str = raw_target.get("css") or raw_target.get("test_id") or raw_target.get("name") or raw_target.get("text") or str(raw_target)
        elif isinstance(raw_target, str) and raw_target.strip():
            locator_str = raw_target.strip()

        # Non-fatal screenshot capture: never let screenshot failure abort execution
        ss_bytes = None
        ss_note = None
        try:
            ss_bytes = await browser.page.screenshot(type="png")
        except Exception as ss_err:
            ss_note = f"Screenshot capture failed: {ss_err}"
            logger.debug("Step screenshot capture failed: %s", ss_err)

        import json
        dom_snapshot_val = None
        if dom_before or dom_after:
            dom_snapshot_val = json.dumps({
                "before": dom_before if isinstance(dom_before, (str, dict, list)) else str(dom_before),
                "after": dom_after if isinstance(dom_after, (str, dict, list)) else str(dom_after),
            }, default=str)

        if event_recorder is not None and ctx.execution_id:
            try:
                from app.infrastructure.database.session import async_session_factory
                from app.modules.executions.evidence_service import EvidenceService
                from app.modules.executions.evidence_model import EvidenceType, EvidenceStatus

                async with async_session_factory() as db:
                    ev_svc = EvidenceService(db)
                    step_id_val = ctx.current_step_id or f"step_{step_index}"
                    if ss_bytes:
                        await ev_svc.capture_screenshot(
                            execution_id=uuid.UUID(ctx.execution_id),
                            screenshot_bytes=ss_bytes,
                            title=f"Step {step_index} execution",
                            description=f"Action {action_type} on {raw_action.get('target', '')}",
                            purpose="step_evidence",
                            step_id=step_id_val,
                            extra_data={
                                "step_index": step_index,
                                "step_id": step_id_val,
                                "action_type": action_type,
                            },
                            dom_snapshot=dom_snapshot_val,
                            a11y_tree=a11y_tree,
                            network_log=step_network if step_network else None,
                            element_locator=locator_str,
                            timestamp_range=[action_started_clock, time.monotonic()],
                            note=ss_note,
                        )
                    else:
                        await ev_svc.create(
                            execution_id=uuid.UUID(ctx.execution_id),
                            type=EvidenceType.SCREENSHOT.value,
                            title=f"Step {step_index} execution",
                            purpose="step_evidence",
                            step_id=step_id_val,
                            description=f"Action {action_type} on {raw_action.get('target', '')}",
                            status=EvidenceStatus.CAPTURED.value,
                            dom_snapshot=dom_snapshot_val,
                            a11y_tree=a11y_tree,
                            network_log=step_network if step_network else None,
                            element_locator=locator_str,
                            timestamp_range=[action_started_clock, time.monotonic()],
                            note=ss_note or "Screenshot not captured",
                        )
                    await db.commit()
            except Exception as ev_err:
                logger.warning("Step %d evidence capture failed (non-fatal): %s", step_index, ev_err)

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
    def _extract_step_target_url(step: dict | str | None, base_url: str = "") -> str | None:
        """Extract a valid target navigation URL from various step formats."""
        if not step:
            return None
        if isinstance(step, str):
            match = re.search(r"https?://\S+", step)
            if match:
                return match.group(0)
            return None
        if not isinstance(step, dict):
            return None

        raw_target = step.get("target")
        target_dict = raw_target if isinstance(raw_target, dict) else {}
        target_str = raw_target if isinstance(raw_target, str) else ""

        candidate = (
            step.get("url")
            or step.get("value")
            or (target_dict.get("url") or target_dict.get("value"))
            or (target_str if (target_str.startswith("http://") or target_str.startswith("https://") or target_str.startswith("/")) else None)
        )
        if candidate and isinstance(candidate, str):
            candidate_clean = candidate.strip()
            if candidate_clean.startswith("http://") or candidate_clean.startswith("https://"):
                return candidate_clean
            if candidate_clean.startswith("/") and base_url:
                from urllib.parse import urljoin
                return urljoin(base_url, candidate_clean)
            if candidate_clean.startswith("/"):
                return candidate_clean
        return None

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
    ) -> bool:
        """Capture evidence after successful verification.

        Creates:
        1. Verification evidence (structured proof)
        2. Screenshot evidence (visual proof of final state)
        Never crashes execution on storage/DB failure.
        Standalone/test runs (no event_recorder) skip persistence entirely.
        """
        if event_recorder is None:
            return True

        execution_id = uuid.UUID(ctx.execution_id)
        try:
            persisted = await asyncio.wait_for(
                self._capture_evidence_inner(
                    ctx, browser, verification, event_recorder, execution_id
                ),
                timeout=8.0,
            )
            return True if persisted is None else persisted
        except asyncio.TimeoutError:
            logger.warning("Evidence capture timed out for %s", execution_id)
            return False
        except Exception as e:
            logger.warning("Evidence capture overall failed: %s", e)
            return False

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
    ) -> bool | None:
        evidence_written = False
        try:
            if not await self._execution_row_exists(execution_id):
                logger.debug(
                    "Skip evidence for %s — no execution row (standalone run)",
                    execution_id,
                )
                return None

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
                            step_id_val = getattr(ctx, "current_step_id", None) or f"step_{ctx.current_step_index}"
                            dom_snap = await browser.get_dom_snapshot() if hasattr(browser, "get_dom_snapshot") else ""
                            verification_evidence = await evidence_service.create_verification_evidence(
                                execution_id=execution_id,
                                title=title,
                                description=description,
                                purpose="verification",
                                step_id=step_id_val,
                                checks=[c.to_dict() for c in verification.checks],
                                dom_snapshot=dom_snap or None,
                                note=f"Verification passed: {description}",
                            )
                            if verification_evidence and "id" in verification_evidence:
                                verification.evidence_ids.append(verification_evidence["id"])
                            evidence_written = verification_evidence is not None
                        except Exception as e:
                            logger.warning("Could not persist verification evidence: %s", e)

                # 2. Capture screenshot of final verified state
                try:
                    screenshot_bytes = await browser.page.screenshot(type="png")
                    step_id_val = getattr(ctx, "current_step_id", None) or f"step_{ctx.current_step_index}"
                    dom_snap = await browser.get_dom_snapshot() if hasattr(browser, "get_dom_snapshot") else ""
                    if screenshot_bytes:
                        screenshot_evidence = await evidence_service.capture_screenshot(
                            execution_id=execution_id,
                            screenshot_bytes=screenshot_bytes,
                            title="Verified browser state",
                            description="Browser state after successful verification",
                            purpose="verification",
                            step_id=step_id_val,
                            extra_data={
                                "step_index": ctx.current_step_index,
                                "step_id": step_id_val,
                                "checkpoint": "verification",
                            },
                            dom_snapshot=dom_snap or None,
                            note="Browser state after successful verification",
                        )
                        if screenshot_evidence and "id" in screenshot_evidence:
                            verification.evidence_ids.append(screenshot_evidence["id"])
                        ctx.record_event(EventTypes.BROWSER_SCREENSHOT, {
                            "title": "Verified browser state",
                            "step_index": ctx.current_step_index,
                            "step_id": step_id_val,
                            "checkpoint": "verification",
                            "purpose": "verification",
                        })
                        await self._emit_events(ctx, event_recorder)
                except Exception as e:
                    logger.warning("Evidence screenshot capture failed: %s", e)
                    ctx.record_event(EventTypes.EVIDENCE_FAILED, {
                        "type": "SCREENSHOT",
                        "error": "Screenshot capture failed",
                    })
                    try:
                        from app.modules.executions.evidence_model import EvidenceType, EvidenceStatus
                        step_id_val = getattr(ctx, "current_step_id", None) or f"step_{ctx.current_step_index}"
                        await evidence_service.create(
                            execution_id=execution_id,
                            type=EvidenceType.SCREENSHOT.value,
                            title="Verified browser state",
                            purpose="verification",
                            step_id=step_id_val,
                            description="Browser state after successful verification",
                            status=EvidenceStatus.CAPTURED.value,
                            note=f"Screenshot capture failed: {e}",
                        )
                    except Exception:
                        pass

                try:
                    await db.commit()
                except Exception as e:
                    logger.warning("Could not commit evidence session: %s", e)
                    return False
                return evidence_written

        except Exception as e:
            logger.warning("Evidence capture overall failed: %s", e)
            return False

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
                timeout=20.0,
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
                step_id_val = getattr(ctx, "current_step_id", None) or f"step_{ctx.current_step_index}"
                dom_snap = await browser.get_dom_snapshot() if hasattr(browser, "get_dom_snapshot") else ""
                try:
                    screenshot_bytes = await browser.page.screenshot(type="png", timeout=5000)
                    if screenshot_bytes:
                        await evidence_service.capture_screenshot(
                            execution_id=execution_id,
                            screenshot_bytes=screenshot_bytes,
                            title="Execution failed",
                            description=f"Browser state at failure: {error_message}",
                            purpose="failure",
                            step_id=step_id_val,
                            extra_data={
                                "step_index": ctx.current_step_index,
                                "step_id": step_id_val,
                                "checkpoint": "failure",
                            },
                            dom_snapshot=dom_snap or None,
                            note=f"Failure: {error_message}",
                        )
                    else:
                        from app.modules.executions.evidence_model import EvidenceType, EvidenceStatus
                        await evidence_service.create(
                            execution_id=execution_id,
                            type=EvidenceType.SCREENSHOT.value,
                            title="Execution failed",
                            purpose="failure",
                            step_id=step_id_val,
                            description=f"Browser state at failure: {error_message}",
                            status=EvidenceStatus.CAPTURED.value,
                            dom_snapshot=dom_snap or None,
                            note=f"Screenshot not captured: {error_message}",
                        )
                except Exception as e:
                    logger.warning("Failure screenshot capture failed: %s", e)
                    try:
                        from app.modules.executions.evidence_model import EvidenceType, EvidenceStatus
                        await evidence_service.create(
                            execution_id=execution_id,
                            type=EvidenceType.SCREENSHOT.value,
                            title="Execution failed",
                            purpose="failure",
                            step_id=step_id_val,
                            description=f"Browser state at failure: {error_message}",
                            status=EvidenceStatus.CAPTURED.value,
                            dom_snapshot=dom_snap or None,
                            note=f"Screenshot capture failed: {e}",
                        )
                    except Exception:
                        pass

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

        # Emit all uncommitted events safely without mutating ctx.events
        async with self._emit_lock:
            while ctx._emitted_count < len(ctx.events):
                event = ctx.events[ctx._emitted_count]
                try:
                    await event_recorder(
                        uuid.UUID(ctx.execution_id),
                        event["type"],
                        event.get("data", {}),
                    )
                except Exception as e:
                    logger.warning("Failed to emit event %s, skipping: %s", event.get("type"), e)
                finally:
                    ctx._emitted_count += 1


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
