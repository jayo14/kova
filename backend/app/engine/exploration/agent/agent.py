from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config.settings import get_settings
from app.engine.ai.provider import get_ai_provider
from app.engine.exploration.agent.policy import is_safe_to_click
from app.engine.exploration.agent.sitemap import SiteMap

logger = logging.getLogger(__name__)


class ExplorationAgent:
    def __init__(self, engine, page, event_emitter=None):
        self.engine = engine
        self.page = page
        self.event_emitter = event_emitter
        self.sitemap = SiteMap()
        self._branch_attempts: dict[str, int] = {}

    async def _emit(self, event_type: str, payload: dict):
        if self.event_emitter:
            try:
                await self.event_emitter(event_type, payload)
            except Exception:
                pass

    def _get_budget(self):
        try:
            s = get_settings()
            return {
                "max_wall_clock": getattr(s, "EXPLORATION_MAX_WALL_CLOCK_SECONDS", 600),
                "max_pages": getattr(s, "EXPLORATION_MAX_PAGES", 50),
                "max_actions": getattr(s, "EXPLORATION_MAX_ACTIONS", 200),
                "max_model_calls": getattr(s, "EXPLORATION_MAX_MODEL_CALLS", 100),
            }
        except Exception:
            return {"max_wall_clock": 600, "max_pages": 50, "max_actions": 200, "max_model_calls": 100}

    async def observe_current(self) -> dict[str, Any]:
        try:
            obs = await self.engine._observe_current_page(self.page)
        except Exception as e:
            logger.debug("observe failed: %s", e)
            obs = {"url": self.page.url}
        return obs

    async def _propose_action_ai(self, current_obs: dict[str, Any]) -> dict[str, Any] | None:
        try:
            provider = await get_ai_provider()
        except Exception:
            return None
        try:
            sitemap_summary = self.sitemap.summarize()
            prompt = (
                "You are an exploration agent. Given current page observation and sitemap, propose ONE next exploration action.\n"
                "Allowed actions: open_link, click_control, open_menu_or_tab, expand_accordion, scroll_to_load_more, go_back.\n"
                "Never submit forms, delete, purchase, send messages, logout.\n"
                "Avoid revisiting known states.\n"
                f"Current: {current_obs.get('url')}\n"
                f"Sitemap nodes: {len(sitemap_summary['nodes'])}, edges: {len(sitemap_summary['edges'])}\n"
                "Return JSON with fields: action, target (selector or text or url), reason, confidence.\n"
            )
            resp = await provider.complete(prompt, system_prompt="Return only valid JSON.")
            import json

            data = json.loads(resp.content if hasattr(resp, "content") else str(resp))
            return data
        except Exception as e:
            logger.debug("AI proposal failed: %s", e)
            return None

    async def _propose_action_bfs(self, current_obs: dict[str, Any]) -> dict[str, Any] | None:
        # Generic breadth-first over links and visible controls (no keyword lists)
        links = current_obs.get("routes") or []
        interactive = current_obs.get("interactive_elements") or []
        # Prefer links not seen
        seen = set(n.url_norm for n in self.sitemap.nodes.values())
        from app.engine.exploration.agent.sitemap import normalize_url

        for link in links:
            href = link.get("href") or link.get("url") or ""
            if href and normalize_url(href) not in seen and href.startswith("http"):
                return {"action": "open_link", "target": {"url": href}, "reason": "bfs_unvisited_link", "confidence": 0.6}
        for ctrl in interactive:
            text = ctrl.get("text") or ctrl.get("aria-label") or ""
            if is_safe_to_click(text, ctrl):
                return {"action": "click_control", "target": ctrl, "reason": "bfs_safe_control", "confidence": 0.5}
        return None

    async def _execute_action(self, proposal: dict[str, Any]) -> bool:
        action = proposal.get("action")
        target = proposal.get("target") or {}
        try:
            if action == "open_link":
                url = target.get("url") or target.get("href")
                if url:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    return True
            elif action == "click_control":
                # Try to click safely
                text = target.get("text") or target.get("name") or ""
                if not is_safe_to_click(text, target):
                    return False
                # Try by text/role heuristically without product-specific keywords
                try:
                    locator = self.page.get_by_text(text, exact=False).first
                    if await locator.is_visible(timeout=1000):
                        await locator.click(timeout=5000)
                        return True
                except Exception:
                    pass
            elif action == "scroll_to_load_more":
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)
                return True
            elif action == "go_back":
                try:
                    await self.page.go_back(wait_until="domcontentloaded", timeout=10000)
                    return True
                except Exception:
                    return False
            elif action == "open_menu_or_tab" or action == "expand_accordion":
                text = target.get("text") or ""
                if is_safe_to_click(text, target):
                    try:
                        locator = self.page.get_by_text(text, exact=False).first
                        if await locator.is_visible(timeout=1000):
                            await locator.click(timeout=5000)
                            return True
                    except Exception:
                        pass
            return False
        except Exception as e:
            logger.debug("execute action failed: %s", e)
            return False

    async def run(self, max_steps: int = 50) -> dict[str, Any]:
        budget = self._get_budget()
        steps = 0
        capabilities = []
        no_new_state_count = 0

        while steps < max_steps:
            steps += 1
            try:
                obs = await self.observe_current()
            except Exception:
                obs = {"url": getattr(self.page, "url", "")}

            current_node = self.sitemap.get_or_create_node(obs.get("url") or getattr(self.page, "url", ""), obs)
            self._branch_attempts[current_node.node_id] = self._branch_attempts.get(current_node.node_id, 0) + 1

            await self._emit("exploration.agent.observe", {"url": obs.get("url"), "node_id": current_node.node_id})

            proposal = await self._propose_action_ai(obs)
            if proposal is None:
                proposal = await self._propose_action_bfs(obs)
                if proposal:
                    proposal["source"] = "bfs_fallback"
                    proposal["confidence"] = 0.5
            else:
                proposal["source"] = "ai"

            if not proposal:
                break

            # Validate - basic safety check
            target = proposal.get("target") or {}
            if proposal.get("action") in ("click_control", "open_menu_or_tab", "expand_accordion"):
                if not is_safe_to_click(target.get("text") or target.get("aria-label"), target):
                    # Record as discovered but don't click
                    await self._emit("exploration.agent.discovered_dangerous", {"target": target})
                    break  # or continue without clicking

            prev_nodes = len(self.sitemap.nodes)
            success = await self._execute_action(proposal)
            await asyncio.sleep(0.3)

            obs2 = await self.observe_current()
            new_node = self.sitemap.get_or_create_node(obs2.get("url") or getattr(self.page, "url", ""), obs2)
            if success:
                self.sitemap.add_edge(current_node.node_id, new_node.node_id, proposal)

            await self._emit("exploration.agent.act", {"action": proposal.get("action"), "success": success, "to_node": new_node.node_id})

            if len(self.sitemap.nodes) <= prev_nodes:
                no_new_state_count += 1
            else:
                no_new_state_count = 0

            if no_new_state_count >= 3:
                break  # stop branch when yields no new state

            # Extract capabilities from current observation
            for act in (obs2.get("primary_actions") or []) + (obs2.get("interactive_elements") or []):
                if act.get("text"):
                    capabilities.append({"capability": act.get("text"), "evidence": {"node_id": new_node.node_id, "url": new_node.url_norm}})

            if self.sitemap._pages_visited_count if hasattr(self.sitemap, '_pages_visited_count') else len(self.sitemap.nodes) >= budget.get("max_pages", 50):
                break

        # Rank capabilities
        seen_caps = {}
        for c in capabilities:
            key = str(c.get("capability", "")).lower()
            if key:
                seen_caps[key] = c
        ranked = list(seen_caps.values())

        return {
            "sitemap": self.sitemap.summarize(),
            "capabilities": ranked,
        }
