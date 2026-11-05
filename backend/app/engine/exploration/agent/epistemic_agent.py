"""Autonomous Epistemic Exploration Agent.

Implements an active, hypothesis-driven investigation loop:
Observe -> Update Understanding -> Hypothesize -> Act -> Evaluate -> Learn.

Replaces shallow crawler behavior with an intelligent software investigator
that explores authenticated workspaces, discovers real business workflows,
and maintains an evolving epistemic model of the target application.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlparse

from app.engine.ai.prompt_sanitizer import build_system_prompt_clause, taint_page_content
from app.engine.ai.provider import get_ai_provider, TaskType
from app.engine.exploration.agent.budget import ResourceBudget
from app.engine.exploration.agent.actions import execute_action
from app.engine.exploration.agent.auth_evaluator import AuthStrategyEvaluator
from app.engine.exploration.agent.interruption import (
    InterruptionDecision,
    InterruptionEvaluator,
    InterruptionType,
)
from app.engine.exploration.agent.policy import is_dangerous_control, is_safe_to_click
from app.engine.exploration.agent.schemas import (
    CLICK_ACTIONS,
    FORM_ACTIONS,
    AgentActionProposal,
    DiscoveredCapability,
    ExplorationAction,
)
from app.engine.exploration.agent.sitemap import SiteMap, normalize_url
from app.engine.exploration.agent.temporal import (
    OperationOutcomeStatus,
    TemporalEvaluator,
)
from app.engine.exploration.agent.understanding import (
    ApplicationArea,
    ApplicationUnderstanding,
    EpistemicState,
    InvestigatedCapability,
    InvestigationQuestion,
    SessionAuthState,
)

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET = {
    "max_wall_clock": 600,
    "max_pages": 50,
    "max_actions": 200,
    "max_model_calls": 100,
}
_NO_PROGRESS_LIMIT = 3

_EPISTEMIC_SYSTEM_PROMPT = (
    "You are an autonomous application investigator exploring a web application to understand its purpose, discover its core capabilities, and map real user workflows. "
    "Observe the application structure, forms, and interactive controls. "
    "Investigate authentication opportunities using available credentials or self-registration to reach authenticated application areas. "
    "Explore beyond landing pages into actual workspaces, dashboards, and tool surfaces. "
    "Interact with controls to discover state transitions, created entities, and core capabilities. "
    "Never trigger financial charges, delete data, or send real external communications. "
    "Propose ONE targeted action to advance understanding. Targets must exist in the observation. "
    "Output ONLY JSON matching: {action, target, reason, confidence, expected_effect}. "
    "Allowed actions: open_link, click_control, fill_inputs, submit_form, authenticate, open_menu_or_tab, expand_accordion, scroll_to_load_more, go_back."
)


def _control_name(control: dict[str, Any]) -> str:
    return str(
        control.get("accessible_name")
        or control.get("name")
        or control.get("label")
        or control.get("text")
        or control.get("aria-label")
        or ""
    ).strip()


def _control_action(control: dict[str, Any]) -> ExplorationAction:
    role = str(control.get("role") or control.get("type") or "").lower()
    if role in ("tab", "menuitem", "menu"):
        return ExplorationAction.OPEN_MENU_OR_TAB
    if role in ("summary",) or control.get("aria-expanded") is not None:
        return ExplorationAction.EXPAND_ACCORDION
    return ExplorationAction.CLICK_CONTROL


def _match_control(target: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any] | None:
    selector = target.get("selector")
    text = str(target.get("text") or target.get("name") or "").strip().lower()
    for control in observation.get("controls") or []:
        if selector and control.get("selector") and selector == control.get("selector"):
            return control
        if text and _control_name(control).lower() == text:
            return control
    return None


def _action_category(proposal: AgentActionProposal) -> str:
    """Categorize an exploration action for budget tracking."""
    action = proposal.action
    if action == ExplorationAction.AUTHENTICATE:
        return "auth"
    if action in (ExplorationAction.DISMISS_INTERRUPTION, ExplorationAction.COMPLETE_INTERRUPTION):
        return "obstacle"
    if action == ExplorationAction.OPEN_LINK:
        target = proposal.target or {}
        url = str(target.get("url") or target.get("href") or "").lower()
        if any(k in url for k in ("/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up", "/auth")):
            return "auth"
        return "discovery"
    if action in (ExplorationAction.CLICK_CONTROL, ExplorationAction.OPEN_MENU_OR_TAB, ExplorationAction.EXPAND_ACCORDION):
        return "discovery"
    if action in (ExplorationAction.FILL_INPUTS, ExplorationAction.SUBMIT_FORM):
        target = proposal.target or {}
        if target.get("is_signup") or any(
            k in str(target.get("url") or target.get("href") or "").lower()
            for k in ("/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up", "/auth")
        ):
            return "auth"
        return "discovery"
    if action == ExplorationAction.SCROLL_TO_LOAD_MORE:
        return "discovery"
    if action == ExplorationAction.GO_BACK:
        return "discovery"
    return "discovery"


def _action_identity(node_id: str, proposal: AgentActionProposal) -> str:
    target = proposal.target or {}
    key = (
        target.get("url")
        or target.get("href")
        or target.get("selector")
        or target.get("text")
        or target.get("name")
        or ("signup" if target.get("is_signup") else "")
        or str((target.get("credentials") or {}).get("email") or "")
    )
    return f"{node_id}:{proposal.action.value}:{str(key).strip().lower()}"


def _origin(url: str | None) -> str:
    try:
        parsed = urlparse(str(url or ""))
        return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    except Exception:
        return ""


def _same_origin_url(base_url: str | None, candidate: Any, origin: str) -> str | None:
    if not candidate:
        return None
    try:
        absolute = urljoin(str(base_url or origin or ""), str(candidate))
    except Exception:
        return None
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    if origin and f"{parsed.scheme}://{parsed.netloc}" != origin:
        return None
    return absolute.split("#", 1)[0]


def _prompt_view(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": observation.get("url"),
        "title": observation.get("title"),
        "headings": observation.get("headings"),
        "links": [
            {"name": link.get("name"), "href": link.get("href"), "selector": link.get("selector")}
            for link in observation.get("links") or []
        ],
        "controls": [
            {
                "name": _control_name(control),
                "role": control.get("role"),
                "selector": control.get("selector"),
                "type": control.get("type"),
            }
            for control in observation.get("controls") or []
        ],
        "forms": observation.get("forms"),
        "dialogs": observation.get("dialogs"),
    }


class EpistemicExplorationAgent:
    """Intelligent exploration agent driven by evolving epistemic understanding."""

    def __init__(
        self,
        engine: Any,
        page: Any,
        event_emitter: Callable[[str, dict], Any] | None = None,
        *,
        provider: Any | None = None,
        budget: dict[str, int] | None = None,
        credentials: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.engine = engine
        self.page = page
        self.event_emitter = event_emitter
        self.provider = provider
        self._provider_resolved = provider is not None
        self.credentials = credentials or {}
        self.sitemap = SiteMap()
        # Backward-compatible budget: accept dict with max_actions or ResourceBudget fields
        _budget = budget or {}
        total_effort = float(_budget.get("total_effort", _budget.get("max_actions", 100)))
        self.budget = ResourceBudget(
            total_effort=total_effort,
            max_wall_clock=float(_budget.get("max_wall_clock", 600)),
            max_pages=int(_budget.get("max_pages", 50)),
        )
        self._clock = clock
        self._started_at = clock()
        self._actions_taken = 0
        self._model_calls = 0
        self._attempted: set[str] = set()
        self._dangerous: list[dict[str, Any]] = []
        self._capabilities: dict[str, DiscoveredCapability] = {}
        self._origin = ""
        self._history: list[str] = []
        self._pending_obs: dict[str, Any] | None = None

        # Epistemic application understanding
        self.understanding = ApplicationUnderstanding(
            target_url=getattr(page, "url", "") or "",
            auth_credentials_available=bool(self.credentials),
        )
        self._last_proposal: AgentActionProposal | None = None
        self._last_obs: dict[str, Any] | None = None

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.event_emitter:
            return
        try:
            await self.event_emitter(event_type, payload)
        except Exception:
            logger.debug("Event emitter failed: %s", event_type, exc_info=True)

    async def _emit_progress(self, message: str, status: str = "completed") -> None:
        await self._emit("progress", {
            "id": f"exp-agent-{int(time.time()*1000)}",
            "message": message,
            "status": status,
        })

    def _resolve_provider(self) -> Any | None:
        if self._provider_resolved:
            return self.provider
        self._provider_resolved = True
        try:
            self.provider = get_ai_provider()
        except Exception:
            self.provider = None
        return self.provider

    def _budget_exhausted(self) -> bool:
        return self.budget.termination_reason is not None

    async def observe_current(self) -> dict[str, Any]:
        fallback_url = getattr(self.page, "url", "") or ""
        try:
            raw = await self.engine._observe_current_page(self.page)
        except Exception:
            logger.debug("Page observation failed", exc_info=True)
            raw = {}
        return self._normalize_observation(raw or {}, fallback_url)

    def _normalize_observation(self, raw: dict[str, Any], fallback_url: str) -> dict[str, Any]:
        url = raw.get("url") or getattr(self.page, "url", None) or fallback_url
        self._origin = self._origin or _origin(url)
        elements = [e for e in (raw.get("elements") or []) if isinstance(e, dict)]
        interactive = [e for e in (raw.get("interactive_elements") or []) if isinstance(e, dict)]
        if not interactive:
            interactive = [
                e for e in elements
                if e.get("type") in ("button", "link", "tab", "menuitem", "summary")
            ]

        links: list[dict[str, Any]] = []
        controls: list[dict[str, Any]] = []
        for element in elements or interactive:
            kind = (element.get("type") or element.get("role") or "").lower()
            href = element.get("href") or element.get("url")
            if kind == "link" or (element.get("role") == "link" and href):
                resolved = _same_origin_url(url, href, self._origin)
                if resolved:
                    entry = dict(element)
                    entry["href"] = resolved
                    links.append(entry)
            elif kind in ("button", "tab", "menuitem", "summary", "switch", "checkbox"):
                controls.append(dict(element))

        for route in raw.get("routes") or []:
            if not isinstance(route, dict):
                continue
            resolved = _same_origin_url(url, route.get("href") or route.get("url") or route.get("path"), self._origin)
            if resolved and all(link.get("href") != resolved for link in links):
                links.append({"type": "link", "name": route.get("text") or route.get("path") or resolved, "href": resolved})

        return {
            **raw,
            "url": url,
            "title": raw.get("title"),
            "headings": raw.get("headings") or [],
            "forms": raw.get("forms") or [],
            "dialogs": raw.get("dialogs") or [],
            "alerts": raw.get("alerts") or [],
            "links": links,
            "controls": controls,
            "interactive_elements": interactive,
            "primary_actions": raw.get("primary_actions") or [e for e in elements if e.get("type") == "button"][:20],
            "routes": [{"url": link["href"], "text": link.get("name")} for link in links],
        }

    async def run(self, max_steps: int | None = None) -> dict[str, Any]:
        """Execute the epistemic investigation loop until goals are met or budget exhausted."""
        step_limit = max_steps if max_steps is not None else int(self.budget.total_effort)
        steps = 0
        no_progress = 0
        termination = "frontier_empty"

        while steps < step_limit:
            # Cancellation checks
            if (
                getattr(self.engine, "_is_cancelled", False)
                or (hasattr(self.engine, "_cancel_event") and self.engine._cancel_event.is_set())
            ):
                raise asyncio.CancelledError("Exploration cancelled during agent run")

            from app.engine.execution.control import check_cancel_flag, is_project_deleted

            exploration_id = getattr(self.engine, "exploration_id", None)
            if exploration_id and await check_cancel_flag(str(exploration_id)):
                if hasattr(self.engine, "request_cancel"):
                    self.engine.request_cancel()
                raise asyncio.CancelledError("Exploration cancelled via control flag")

            project_id = getattr(self.engine, "project_id", None)
            if project_id and await is_project_deleted(str(project_id)):
                if hasattr(self.engine, "request_cancel"):
                    self.engine.request_cancel()
                raise asyncio.CancelledError("Project was deleted")

            if self._budget_exhausted():
                termination = "budget_exhausted"
                break

            steps += 1

            # 1. Observe current state
            if self._pending_obs is not None:
                observation = self._pending_obs
                self._pending_obs = None
            else:
                observation = await self.observe_current()

            node = self.sitemap.get_or_create_node(observation["url"], observation)
            await self._emit(
                "exploration.agent.observe",
                {"url": node.url_norm, "node_id": node.node_id, "step": steps},
            )

            # Record capabilities and dangerous controls
            self._record_capabilities(observation, node)
            self._record_dangerous(observation, node)
            self._update_understanding_from_obs(observation, node)

            if self._last_proposal and self._last_obs:
                self._evaluate_action_outcome(self._last_obs, observation, self._last_proposal)

            # 2. Propose next action
            proposal = await self._propose(observation, node)
            if proposal is None:
                termination = "frontier_empty"
                break

            identity = _action_identity(node.node_id, proposal)
            if identity in self._attempted:
                termination = "frontier_empty"
                break
            self._attempted.add(identity)

            # 3. Validate proposal
            if not self._validated(proposal, observation):
                await self._emit(
                    "exploration.agent.reject_proposal",
                    {"action": proposal.action.value, "reason": proposal.reason},
                )
                no_progress += 1
                if no_progress >= _NO_PROGRESS_LIMIT:
                    termination = "no_new_state"
                    break
                continue

            # 4. Execute action
            before_url = observation["url"]
            before_nodes_count = len(self.sitemap.nodes)
            self._last_obs = observation
            self._last_proposal = proposal

            is_interruption_action = (
                proposal.action in (
                    ExplorationAction.DISMISS_INTERRUPTION,
                    ExplorationAction.COMPLETE_INTERRUPTION,
                )
                or proposal.source == "interruption_handler"
            )

            is_auth_submission = (
                proposal.action == ExplorationAction.AUTHENTICATE
                or (proposal.source == "auth_strategy_evaluator" and proposal.action != ExplorationAction.OPEN_LINK)
            )

            if is_auth_submission:
                await self._emit_progress("Verifying application access...", status="active")

            success, detail = await execute_action(self.page, proposal, self.credentials, history=self._history)

            # 5. Post-action observation (needed for budget evidence assessment)
            after_obs = await self.observe_current()
            self._pending_obs = after_obs
            after_url = after_obs["url"]
            after_node = self.sitemap.get_or_create_node(after_url, after_obs)

            # Categorize the action for budget tracking
            action_category = _action_category(proposal)
            # Determine if this action produced new evidence
            evidence_gained = (
                after_node.url_norm != node.url_norm
                or len(after_obs.get("controls") or []) != len(observation.get("controls") or [])
                or len(after_obs.get("links") or []) != len(observation.get("links") or [])
                or self.understanding.is_currently_authenticated
            )
            if not self.budget.spend(action_category, evidence_gained=evidence_gained, step=steps):
                termination = self.budget.termination_reason or "budget_exhausted"
                break

            if success:
                self.sitemap.add_edge(node.node_id, after_node.node_id, proposal.model_dump(mode="json"))
                self.understanding.record_transition(
                    from_url=before_url,
                    action=proposal.model_dump(mode="json"),
                    to_url=after_url,
                    effect=detail,
                )

            # Evaluate interruption resolution outcomes
            if is_interruption_action:
                dialogs_before = observation.get("dialogs") or []
                dialogs_after = after_obs.get("dialogs") or []
                diag_title = proposal.target.get("dialog_title") or "Dialog"
                is_closed = len(dialogs_after) < len(dialogs_before) or not any(
                    str(d.get("title") or d.get("accessible_name") or "") == diag_title
                    for d in dialogs_after
                )
                if is_closed or success:
                    self.understanding.record_interruption(
                        title=diag_title,
                        interruption_type="optional_prompt" if proposal.action == ExplorationAction.DISMISS_INTERRUPTION else "required_setup",
                        decision="dismiss" if proposal.action == ExplorationAction.DISMISS_INTERRUPTION else "complete_required",
                        resolution_action=proposal.action.value,
                        resolved=True,
                        underlying_accessible=True,
                    )
                    await self._emit_progress("Dialog dismissed; underlying workspace accessible")
                    await self._emit_progress("Resuming application investigation")

            # Evaluate authentication verification outcomes with temporal awareness
            if is_auth_submission:
                pending_host = None
                if hasattr(self.engine, "_browser") and self.engine._browser:
                    pending_host = self.engine._browser.get_slowest_pending_host()

                eval_res = TemporalEvaluator.evaluate_operation(
                    proposal, observation, after_obs, self.understanding, pending_host=pending_host
                )

                if eval_res.status == OperationOutcomeStatus.TRANSIENTLY_BLOCKED:
                    await self._emit_progress(eval_res.event_description, status="active")
                    # Adaptively wait for pending dependency to resolve
                    settle_data = await TemporalEvaluator.adaptively_wait_for_settlement(
                        self.page,
                        pending_checker=lambda: self.engine._browser.get_slowest_pending_host() if getattr(self.engine, "_browser", None) else None,
                        max_wait_s=eval_res.suggested_wait_s,
                    )
                    after_obs = await self.observe_current()
                    self._pending_obs = after_obs
                    after_url = after_obs["url"]
                    after_node = self.sitemap.get_or_create_node(after_url, after_obs)
                    if eval_res.affected_dependency:
                        self.understanding.update_dependency(eval_res.affected_dependency, is_ready=True, status="ready")
                        await self._emit_progress(f"Backend availability confirmed: {eval_res.affected_dependency} responded")

                elif eval_res.status == OperationOutcomeStatus.PENDING:
                    await self._emit_progress(eval_res.event_description, status="active")
                    # Wait for redirect in flight
                    await asyncio.sleep(2.0)
                    after_obs = await self.observe_current()
                    self._pending_obs = after_obs
                    after_url = after_obs["url"]
                    after_node = self.sitemap.get_or_create_node(after_url, after_obs)

                self._update_understanding_from_obs(after_obs, after_node)
                after_path = urlparse(after_url).path.lower()
                is_after_auth_area = any(p in after_path for p in ("/login", "/register", "/signup", "/signin", "/sign-in", "/auth"))

                is_now_auth = (
                    not is_after_auth_area
                    and (
                        self.understanding.is_currently_authenticated
                        or any(k in after_url.lower() for k in ("/dashboard", "/workspace", "/app", "/console", "/account", "/home"))
                    )
                )
                if not is_now_auth and not is_after_auth_area and hasattr(self.page, "evaluate"):
                    try:
                        storage_auth = await self.page.evaluate("""() => {
                            return Object.keys(localStorage).some(k => k.includes('token') || k.includes('user') || k.includes('auth')) ||
                                   document.cookie.includes('token') || document.cookie.includes('auth');
                        }""")
                        if storage_auth:
                            is_now_auth = True
                    except Exception:
                        pass

                target_dict = proposal.target or {}
                if target_dict.get("is_signup") and not self.understanding.registration_submitted:
                    self.understanding.mark_registration_submitted()
                    self.understanding.set_exploration_identity(
                        (target_dict.get("credentials") or {}).get("email"),
                        (target_dict.get("credentials") or {}).get("password"),
                        (target_dict.get("credentials") or {}).get("name"),
                    )
                provider = target_dict.get("provider")
                if provider or any(p in str(target_dict.get("text") or "").lower() for p in ("google", "apple", "github", "microsoft")):
                    strategy_type = "oauth"
                    provider = provider or "google"
                elif target_dict.get("is_signup") or any(k in before_url.lower() for k in ("register", "signup")):
                    strategy_type = "self_registration"
                    provider = None
                else:
                    strategy_type = "native_login"
                    provider = None

                if is_now_auth:
                    self.understanding.is_currently_authenticated = True
                    self.understanding.update_session_auth(SessionAuthState.AUTHENTICATED_SESSION_MAINTAINED)
                    if (proposal.target or {}).get("is_signup"):
                        self.understanding.mark_registration_succeeded()
                    self.understanding.record_auth_attempt(
                        strategy_type,
                        provider,
                        success=True,
                        outcome=f"Access granted: Reached {after_url}",
                    )
                    await self._emit_progress(f"Application access verified: Successfully entered application workspace at {after_url}")
                elif eval_res.status == OperationOutcomeStatus.INCONCLUSIVE:
                    self.understanding.record_auth_attempt(
                        strategy_type,
                        provider,
                        success=False,
                        outcome=f"Inconclusive (remained at {after_url})",
                    )
                    await self._emit_progress(f"Registration outcome remains inconclusive at {after_url}; checking session state")
                else:
                    self.understanding.record_auth_attempt(
                        strategy_type,
                        provider,
                        success=False,
                        outcome=f"Did not grant application access (remained at {after_url})",
                    )
                    await self._emit_progress(f"Application access not established: Remained at {after_url}")
                    failed_same = sum(
                        1 for a in self.understanding.attempted_auth_strategies
                        if a.get("type") == strategy_type and not a.get("success")
                    )
                    if failed_same >= 2:
                        self.understanding.mark_auth_blocked("Repeated authentication attempts did not establish a session")
            elif proposal.action == ExplorationAction.OPEN_LINK:
                after_path = urlparse(after_url).path.lower()
                is_after_auth_area = any(p in after_path for p in ("/login", "/register", "/signup", "/signin", "/sign-in", "/auth"))
                if is_after_auth_area and not self.understanding.is_currently_authenticated:
                    await self._emit_progress(f"Navigated to authentication surface: {after_url}")

            await self._emit(
                "exploration.agent.act",
                {
                    "action": proposal.action.value,
                    "success": success,
                    "node_id": node.node_id,
                    "to_node": after_node.node_id,
                    "source": proposal.source,
                },
            )

            moved = after_node.url_norm != node.url_norm
            if len(self.sitemap.nodes) > before_nodes_count or moved:
                no_progress = 0
            else:
                no_progress += 1
                if no_progress >= _NO_PROGRESS_LIMIT:
                    termination = "no_new_state"
                    break

            if self._budget_exhausted():
                termination = "budget_exhausted"
                break

        return {
            "sitemap": self.sitemap.summarize(),
            "capabilities": self._ranked_capabilities(),
            "dangerous_controls": list(self._dangerous),
            "termination": termination,
            "understanding": self.understanding.summarize_understanding(),
            "stats": {
                "steps": steps,
                "actions": self.budget.actions_taken,
                "model_calls": self._model_calls,
                "pages": len(self.sitemap.nodes),
                "elapsed_seconds": round(self._clock() - self._started_at, 3),
                "budget": self.budget.summary(),
            },
        }

    def _validated(self, proposal: AgentActionProposal, observation: dict[str, Any]) -> bool:
        if proposal.action in (
            ExplorationAction.DISMISS_INTERRUPTION,
            ExplorationAction.COMPLETE_INTERRUPTION,
        ):
            return True
        if proposal.action == ExplorationAction.SCROLL_TO_LOAD_MORE:
            return True
        if proposal.action == ExplorationAction.GO_BACK:
            return bool(self._origin)
        if proposal.action == ExplorationAction.AUTHENTICATE:
            return True
        if proposal.action == ExplorationAction.OPEN_LINK:
            url = proposal.target.get("url") or proposal.target.get("href")
            return bool(_same_origin_url(observation.get("url") or self._origin, url, self._origin))
        if proposal.action in CLICK_ACTIONS:
            control = _match_control(proposal.target, observation)
            if control is None:
                return False
            return is_safe_to_click(_control_name(control), control)
        if proposal.action in FORM_ACTIONS:
            control = _match_control(proposal.target, observation)
            name = _control_name(control) if control else str(proposal.target.get("text") or "")
            return not is_dangerous_control(name, control or proposal.target)
        return False

    def _update_understanding_from_obs(self, obs: dict[str, Any], node: Any) -> None:
        url = obs.get("url") or ""
        title = obs.get("title") or ""
        path = urlparse(url).path.lower()

        if not self.understanding.app_name and title:
            parts = [p.strip() for p in title.split("|") if p.strip()]
            self.understanding.app_name = parts[0] if parts else title

        is_auth_path = any(k in path for k in ("/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up", "/auth"))
        has_password_input = any(
            (i.get("type") or "").lower() == "password" or "password" in (i.get("name") or "").lower()
            for i in obs.get("inputs") or []
        )
        is_auth_area = is_auth_path or has_password_input

        # Check for affirmative authenticated evidence
        controls = obs.get("controls") or []
        links = obs.get("links") or []
        all_interactive = controls + links
        has_signout_control = any(
            any(kw in ((c.get("name") or c.get("text") or c.get("label") or "").lower()) for kw in ("sign out", "signout", "log out", "logout"))
            for c in all_interactive
        )
        is_workspace = any(k in path for k in ("/app", "/dashboard", "/workspace", "/project", "/reports", "/console", "/home"))
        is_authenticated = (
            has_signout_control
            or (self.understanding.is_currently_authenticated and not is_auth_area)
            or (is_workspace and not is_auth_area)
        )

        if is_authenticated and not self.understanding.is_currently_authenticated:
            self.understanding.is_currently_authenticated = True
            self.understanding.update_session_auth(SessionAuthState.AUTHENTICATED_SESSION_MAINTAINED)

        if is_auth_area:
            area_name = "Authentication"
        elif is_authenticated:
            area_name = "User Workspace" if path in ("", "/") else f"Workspace: {path}"
        elif path in ("", "/"):
            area_name = "Landing"
        else:
            area_name = f"Section {path}"
        self.understanding.record_area(area_name, path, is_authenticated=is_authenticated, url=url)

        if is_auth_area:
            self.understanding.auth_required = True
            self.understanding.auth_type = "password_form"

        # Register discovered authentication options
        analysis = AuthStrategyEvaluator.analyze_surface(obs, url)
        for opt in analysis.options:
            self.understanding.record_auth_method(
                method_type=opt.method_type,
                provider=opt.provider,
                label=opt.label,
                entry_selector=opt.selector,
                entry_url=opt.target_url,
                viable=True,
            )
        if analysis.is_auth_surface:
            self.understanding.auth_required = True
            if analysis.has_native_login:
                self.understanding.auth_type = "credentials"
            elif analysis.has_registration_form:
                self.understanding.auth_type = "registration"

    def _evaluate_action_outcome(
        self,
        prev_obs: dict[str, Any],
        curr_obs: dict[str, Any],
        proposal: AgentActionProposal,
    ) -> None:
        target = proposal.target or {}
        name = target.get("text") or target.get("name") or proposal.action.value
        url_before = prev_obs.get("url") or ""
        url_after = curr_obs.get("url") or ""

        if url_after != url_before:
            outcome = f"Navigated from {url_before} to {url_after}"
            self.understanding.confirm_capability(name, proposal.model_dump(mode="json"), outcome)
            after_path = urlparse(url_after).path.lower()
            is_after_auth_area = any(p in after_path for p in ("/login", "/register", "/signup", "/signin", "/sign-in", "/auth"))
            if not is_after_auth_area:
                if "login" in url_before.lower():
                    self.understanding.is_currently_authenticated = True
                    self.understanding.answer_question("Can we authenticate with project credentials?", "Authentication succeeded; redirected to application workspace")
                elif "register" in url_before.lower() or "signup" in url_before.lower():
                    self.understanding.is_currently_authenticated = True
                    self.understanding.answer_question("Can a new user register for this application?", "Registration succeeded; reached application workspace")

    async def _propose(
        self, observation: dict[str, Any], node: Any
    ) -> AgentActionProposal | None:
        curr_url = observation.get("url") or getattr(self.page, "url", "") or ""

        # 1. Investigate and handle interface obstructions (modals, dialogs, popovers, onboarding)
        for dialog in observation.get("dialogs") or []:
            analysis = InterruptionEvaluator.evaluate(dialog, observation, self.understanding)
            if analysis.decision != InterruptionDecision.PRESERVE_AND_DEFER:
                interruption_prop = InterruptionEvaluator.propose_action_for_interruption(analysis, dialog, node.node_id)
                if interruption_prop is not None:
                    identity = _action_identity(node.node_id, interruption_prop)
                    if identity not in self._attempted:
                        await self._emit_progress(f"Detected interface interruption: {analysis.title or 'Dialog'}")
                        await self._emit_progress(f"Investigating dialog requirements: {analysis.interruption_type.value.replace('_', ' ')}")
                        if analysis.decision == InterruptionDecision.DISMISS:
                            await self._emit_progress(f"Determined that the prompt is optional: {analysis.reason}")
                        elif analysis.decision == InterruptionDecision.COMPLETE_REQUIRED:
                            await self._emit_progress(f"Required setup discovered: {analysis.title}")
                        await self._emit_progress(analysis.event_description, status="active")
                        return interruption_prop.with_source("interruption_handler")

        analysis = AuthStrategyEvaluator.analyze_surface(observation, curr_url)

        # Evaluate authentication doors before doing blind BFS/crawling
        if not self.understanding.is_currently_authenticated and not self.understanding.auth_blocked:
            if analysis.is_auth_surface or analysis.has_registration_link or analysis.has_native_login or analysis.has_registration_form:
                strategy, justification = AuthStrategyEvaluator.select_strategy(analysis, self.credentials, self.understanding)
                if strategy is not None:
                    summary = analysis.options_summary()
                    await self._emit_progress(f"Discovered authentication options: {summary}")
                    await self._emit_progress("Evaluating available access: Checking configured credentials and registration requirements")
                    await self._emit_progress(f"Selected {strategy.label}: {justification}")
                    self.understanding.selected_auth_strategy = strategy.label

                    auth_proposal = AuthStrategyEvaluator.propose_action_for_strategy(strategy, self.credentials, node.node_id, self.understanding)
                    if auth_proposal is not None:
                        identity = _action_identity(node.node_id, auth_proposal)
                        if identity not in self._attempted:
                            await self._emit_progress(f"Executing selected strategy: {auth_proposal.reason}", status="active")
                            return auth_proposal.with_source("auth_strategy_evaluator")

        provider = self._resolve_provider()
        if provider is not None and self._model_calls < int(self.budget.total_effort):
            proposal = await self._propose_ai(provider, observation, node)
            if proposal is not None:
                return proposal.with_source("ai")
        proposal = self._propose_bfs(observation, node)
        if proposal is not None:
            proposal = proposal.with_source("bfs_fallback")
        return proposal

    async def _propose_ai(
        self, provider: Any, observation: dict[str, Any], node: Any
    ) -> AgentActionProposal | None:
        self._model_calls += 1
        prompt = (
            "Current URL: "
            + str(observation.get("url"))
            + "\nVisited nodes: "
            + str(len(self.sitemap.nodes))
            + "\nAlready attempted actions: "
            + str(len(self._attempted))
            + "\nEpistemic State & Open Questions:\n"
            + json.dumps(self.understanding.summarize_understanding(), indent=2)
            + "\nObservation:\n"
            + taint_page_content(json.dumps(_prompt_view(observation), sort_keys=True)[:12000])
            + build_system_prompt_clause()
        )
        try:
            return await provider.generate_structured(
                _EPISTEMIC_SYSTEM_PROMPT,
                prompt,
                AgentActionProposal,
                task_type=TaskType.NEXT_ACTION,
            )
        except Exception as exc:
            logger.debug("AI epistemic proposal failed: %s", exc)
            return None

    def _propose_bfs(self, observation: dict[str, Any], node: Any) -> AgentActionProposal | None:
        seen_urls = {n.url_norm for n in self.sitemap.nodes.values()}
        is_authenticated = self.understanding.is_currently_authenticated

        def _link_priority(link: dict[str, Any]) -> int:
            href = str(link.get("href") or "").lower()
            name = str(link.get("name") or "").lower()
            if is_authenticated:
                if any(k in href for k in ("/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up", "/auth/login")):
                    return -100
            else:
                if any(k in href for k in ("/register", "/signup", "/sign-up", "/join", "/login", "/signin", "/sign-in")):
                    return 100
            if any(k in href for k in ("/app", "/dashboard", "/workspace")):
                return 100
            if any(k in name for k in ("get started", "create account", "sign up", "sign in", "log in", "try free", "start free", "try now", "start now", "launch app")):
                return 90 if not is_authenticated else 10
            parsed = urlparse(href)
            if parsed.path and parsed.path not in ("/", "") and not parsed.fragment:
                return 50
            if parsed.path and parsed.path not in ("/", ""):
                return 30
            if parsed.fragment:
                return 10
            return 20

        # 1. Links (prioritizing functional entrances and app paths over static hash fragments)
        candidate_links = observation.get("links") or []
        if is_authenticated:
            candidate_links = [
                l for l in candidate_links
                if not any(k in str(l.get("href") or "").lower() for k in ("/login", "/signin", "/sign-in", "/register", "/signup", "/sign-up", "/auth"))
            ]
        candidate_links = sorted(candidate_links, key=_link_priority, reverse=True)
        for link in candidate_links:
            href = link.get("href")
            if not href:
                continue
            href_norm = normalize_url(href)
            if href_norm in seen_urls and href_norm != node.url_norm:
                continue
            if href_norm != node.url_norm:
                proposal = AgentActionProposal(
                    action=ExplorationAction.OPEN_LINK,
                    target={"url": href, "text": link.get("name") or href, "selector": link.get("selector")},
                    reason="unvisited link",
                    confidence=0.6,
                )
                if _action_identity(node.node_id, proposal) not in self._attempted:
                    return proposal

        # 2. Controls
        attempted_failed_oauth = {
            att.get("provider") or "oauth"
            for att in self.understanding.attempted_auth_strategies
            if att.get("type") == "oauth" and not att.get("success")
        }
        for control in observation.get("controls") or []:
            name = _control_name(control)
            lower_name = name.lower()
            if any(p in lower_name for p in ("google", "apple", "github", "microsoft", "sso")) and (attempted_failed_oauth or not self.credentials):
                # Do not repeat failed OAuth or blindly click OAuth controls through BFS
                continue
            if not is_safe_to_click(name, control):
                continue
            proposal = AgentActionProposal(
                action=_control_action(control),
                target={
                    "text": name,
                    "selector": control.get("selector"),
                    "role": control.get("role"),
                    "tag": control.get("tag"),
                    "type": control.get("type"),
                },
                reason="visible safe control",
                confidence=0.5,
            )
            if _action_identity(node.node_id, proposal) not in self._attempted:
                return proposal

        # 3. Scroll
        if not self._attempted or not any(key.startswith(f"{node.node_id}:") for key in self._attempted):
            return AgentActionProposal(
                action=ExplorationAction.SCROLL_TO_LOAD_MORE,
                target={},
                reason="load deferred content",
                confidence=0.3,
            )

        # 4. Go Back
        if self._history:
            proposal = AgentActionProposal(
                action=ExplorationAction.GO_BACK,
                target={},
                reason="return to reach unvisited links",
                confidence=0.2,
            )
            if _action_identity(node.node_id, proposal) not in self._attempted:
                return proposal

        return None

    def _record_capabilities(self, observation: dict[str, Any], node: Any) -> None:
        for link in observation.get("links") or []:
            self._add_capability(link.get("name") or link.get("href"), "link", node, link, 0.7)
        for control in observation.get("controls") or []:
            kind = "button" if (control.get("type") or "").lower() != "tab" else "tab"
            self._add_capability(_control_name(control), kind, node, control, 0.8)
        for form in observation.get("forms") or []:
            name = form.get("name") or form.get("id") or form.get("action") or "form"
            self._add_capability(str(name), "form", node, form, 0.9)
        for heading in observation.get("headings") or []:
            text = heading.get("text") if isinstance(heading, dict) else heading
            if text:
                self._add_capability(str(text), "section", node, heading, 0.6)
        for dialog in observation.get("dialogs") or []:
            name = dialog.get("title") or dialog.get("name") or "dialog"
            self._add_capability(str(name), "dialog", node, dialog, 0.8)

    def _add_capability(self, name: Any, kind: str, node: Any, evidence: Any, confidence: float) -> None:
        text = str(name or "").strip()
        if not text:
            return
        key = f"{kind}:{text.lower()}"
        existing = self._capabilities.get(key)
        if existing is not None:
            existing.confidence = min(1.0, max(existing.confidence, confidence) + 0.02)
            existing.evidence["seen_count"] = int(existing.evidence.get("seen_count", 1)) + 1
            return
        self._capabilities[key] = DiscoveredCapability(
            name=text[:200],
            kind=kind,
            url=node.url_norm,
            node_id=node.node_id,
            source="observed",
            confidence=confidence,
            evidence={
                "node_id": node.node_id,
                "url": node.url_norm,
                "selector": evidence.get("selector") if isinstance(evidence, dict) else None,
                "seen_count": 1,
            },
        )
        # Feed into ApplicationUnderstanding so journey synthesizers have full workspace capability context
        is_auth = self.understanding.is_currently_authenticated
        preconditions = ["authenticated_session"] if is_auth else []
        self.understanding.record_capability(
            name=text[:200],
            user_goal=f"Use {text[:200]}",
            state=EpistemicState.OBSERVED,
            is_core=is_auth or confidence >= 0.8,
            entry_url=node.url_norm,
            preconditions=preconditions,
        )

    def _record_dangerous(self, observation: dict[str, Any], node: Any) -> None:
        for control in observation.get("controls") or []:
            name = _control_name(control)
            if is_dangerous_control(name, control):
                key = f"{node.node_id}:{name.lower()}"
                if any(item.get("key") == key for item in self._dangerous):
                    continue
                self._dangerous.append(
                    {
                        "key": key,
                        "name": name,
                        "url": node.url_norm,
                        "node_id": node.node_id,
                        "selector": control.get("selector"),
                        "clicked": False,
                    }
                )

    def _ranked_capabilities(self) -> list[dict[str, Any]]:
        ranked = sorted(
            self._capabilities.values(),
            key=lambda c: (c.confidence, c.evidence.get("seen_count", 1), c.name.lower()),
            reverse=True,
        )
        return [c.model_dump(mode="json") for c in ranked]
