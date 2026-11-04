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
from app.engine.exploration.agent.actions import execute_action
from app.engine.exploration.agent.policy import is_dangerous_control, is_safe_to_click
from app.engine.exploration.agent.schemas import (
    CLICK_ACTIONS,
    FORM_ACTIONS,
    AgentActionProposal,
    DiscoveredCapability,
    ExplorationAction,
)
from app.engine.exploration.agent.sitemap import SiteMap, normalize_url
from app.engine.exploration.agent.understanding import (
    ApplicationArea,
    ApplicationUnderstanding,
    EpistemicState,
    InvestigatedCapability,
    InvestigationQuestion,
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


def _action_identity(node_id: str, proposal: AgentActionProposal) -> str:
    target = proposal.target or {}
    key = target.get("url") or target.get("href") or target.get("selector") or target.get("text") or target.get("name") or ""
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
        self.budget = {**_DEFAULT_BUDGET, **(budget or {})}
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
        elapsed = self._clock() - self._started_at
        return (
            elapsed >= self.budget["max_wall_clock"]
            or len(self.sitemap.nodes) >= self.budget["max_pages"]
            or self._actions_taken >= self.budget["max_actions"]
        )

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
        step_limit = max_steps if max_steps is not None else self.budget["max_actions"]
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

            success, detail = await execute_action(self.page, proposal, self.credentials, history=self._history)
            self._actions_taken += 1

            # 5. Post-action observation
            after_obs = await self.observe_current()
            self._pending_obs = after_obs
            after_url = after_obs["url"]
            after_node = self.sitemap.get_or_create_node(after_url, after_obs)

            if success:
                self.sitemap.add_edge(node.node_id, after_node.node_id, proposal.model_dump(mode="json"))
                self.understanding.record_transition(
                    from_url=before_url,
                    action=proposal.model_dump(mode="json"),
                    to_url=after_url,
                    effect=detail,
                )

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
                "actions": self._actions_taken,
                "model_calls": self._model_calls,
                "pages": len(self.sitemap.nodes),
                "elapsed_seconds": round(self._clock() - self._started_at, 3),
            },
        }

    def _validated(self, proposal: AgentActionProposal, observation: dict[str, Any]) -> bool:
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

        is_workspace = any(k in path for k in ("/app", "/dashboard", "/workspace", "/project", "/reports", "/console", "/home"))
        is_authenticated = is_workspace or (not is_auth_area and path not in ("", "/"))

        if is_authenticated and not self.understanding.is_currently_authenticated:
            self.understanding.is_currently_authenticated = True

        area_name = "Authentication" if is_auth_area else ("User Workspace" if is_workspace else ("Landing" if path in ("", "/") else f"Section {path}"))
        self.understanding.record_area(area_name, path, is_authenticated=is_authenticated, url=url)

        if is_auth_area:
            self.understanding.auth_required = True
            self.understanding.auth_type = "password_form"

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
            if "login" in url_before.lower() and "login" not in url_after.lower():
                self.understanding.is_currently_authenticated = True
                self.understanding.answer_question("Can we authenticate with project credentials?", "Authentication succeeded; redirected to application workspace")
            elif "register" in url_before.lower() and "register" not in url_after.lower():
                self.understanding.is_currently_authenticated = True
                self.understanding.answer_question("Can a new user register for this application?", "Registration succeeded; reached application workspace")

    async def _propose(
        self, observation: dict[str, Any], node: Any
    ) -> AgentActionProposal | None:
        provider = self._resolve_provider()
        if provider is not None and self._model_calls < self.budget["max_model_calls"]:
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

        # 1. Links
        for link in observation.get("links") or []:
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
        for control in observation.get("controls") or []:
            name = _control_name(control)
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
