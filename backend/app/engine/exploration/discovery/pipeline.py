from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import settings
from app.engine.ai.reasoner import AgentReasoner
from app.engine.exploration.discovery.ai_assistant import AIAssistant
from app.engine.exploration.discovery.auth_detector import AuthDetector
from app.engine.exploration.discovery.capability_extractor import CapabilityExtractor
from app.engine.exploration.discovery.crawler import DiscoveryCrawler
from app.engine.exploration.discovery.invariant_inferrer import InvariantInferrer
from app.engine.exploration.discovery.persona_detector import PersonaDetector
from app.modules.product_graph.schemas import (
    Action,
    AIProposal,
    Capability,
    DiscoveryResult,
    Goal,
    Invariant,
    Page,
    Persona,
    State,
)
from app.modules.flows.schemas import StateAssertion

logger = logging.getLogger(__name__)


class DiscoveryPipeline:
    def __init__(
        self,
        project_id: uuid.UUID,
        base_url: str,
        depth_budget: int = 3,
        max_pages: int = 50,
        reasoner: AgentReasoner | None = None,
    ):
        self.project_id = project_id
        self.base_url = base_url.rstrip("/")
        self.depth_budget = depth_budget or settings.DISCOVERY_MAX_DEPTH
        self.max_pages = max_pages or settings.DISCOVERY_MAX_PAGES

        self.crawler = DiscoveryCrawler(
            project_id=self.project_id,
            base_url=self.base_url,
            depth_budget=self.depth_budget,
            max_pages=self.max_pages,
        )
        self.auth_detector = AuthDetector()
        self.persona_detector = PersonaDetector(project_id=self.project_id)
        self.capability_extractor = CapabilityExtractor(project_id=self.project_id)
        self.invariant_inferrer = InvariantInferrer(project_id=self.project_id)
        self.ai_assistant = AIAssistant(reasoner=reasoner)

    async def discover(self, browser_page: Any) -> DiscoveryResult:
        """Run full multi-stage product discovery pipeline against a target web application."""
        logger.info("Starting Product Discovery for project %s at %s", self.project_id, self.base_url)

        # Stage 1 & 2: Bootstrap & Crawl
        pages: list[Page] = await self.crawler.crawl(browser_page)

        all_actions: list[Action] = []
        all_capabilities: list[Capability] = []
        all_states: list[State] = []
        ai_proposals: list[AIProposal] = []

        # Stage 3, 4, 5: Inspect pages for auth, personas, actions, and capabilities
        for page in pages:
            try:
                # Navigate to the page if not currently there
                current_url = browser_page.url.split("#")[0].rstrip("/")
                target_url = (self.base_url + page.url_pattern).rstrip("/")
                if current_url != target_url and page.url_pattern != "/":
                    await browser_page.goto(target_url, wait_until="domcontentloaded", timeout=10000)

                # Stage 3: Auth mapping
                await self.auth_detector.inspect_page_auth(browser_page, page)

                # Stage 5: Action & capability extraction
                actions, caps, states = await self.capability_extractor.extract_actions_and_capabilities(
                    browser_page, page
                )

                # Stage 7: AI assistance on ambiguous actions
                proposals = await self.ai_assistant.assist_ambiguous_actions(
                    actions, {"url": page.url_pattern}
                )
                ai_proposals.extend(proposals)

                all_actions.extend(actions)
                all_capabilities.extend(caps)
                all_states.extend(states)

            except Exception as e:
                logger.warning("Pipeline stage failed on page %s: %s", page.url_pattern, e)
                self.crawler.warnings.append(f"Inspection error on {page.url_pattern}: {str(e)}")

        # Stage 4: Persona detection across application
        personas: list[Persona] = await self.persona_detector.detect_personas(browser_page, pages)

        # Detect auth pages and produce AuthCapability rows for Product Graph
        auth_caps = await self.auth_detector.detect_auth(pages, all_actions, personas)
        all_capabilities.extend(auth_caps)

        # Stage 6: Invariant inference
        invariants: list[Invariant] = self.invariant_inferrer.infer_invariants(
            pages, all_actions, all_capabilities
        )

        # Synthesize baseline goals from capabilities and personas
        goals: list[Goal] = []
        for cap in all_capabilities:
            crit: list[StateAssertion] = []
            for mut in (cap.produces_state or []):
                k = mut.key if hasattr(mut, "key") else (mut.get("key") if isinstance(mut, dict) else "")
                v = mut.value if hasattr(mut, "value") else (mut.get("value") if isinstance(mut, dict) else None)
                if k:
                    crit.append(StateAssertion(key=k, value=v, predicate="eq"))
            goals.append(
                Goal(
                    project_id=self.project_id,
                    name=f"Enable {cap.name.replace('_', ' ').title()}",
                    description=cap.description,
                    success_criteria=crit,
                    source="discovered",
                    confidence=cap.confidence,
                )
            )

        # Deduplicate capabilities and states by name/key
        unique_caps: dict[str, Capability] = {}
        for c in all_capabilities:
            if c.name not in unique_caps:
                unique_caps[c.name] = c
            else:
                existing = unique_caps[c.name]
                existing.source_files = list(set(existing.source_files + c.source_files))

        unique_states: dict[str, State] = {}
        for s in all_states:
            if s.key not in unique_states:
                unique_states[s.key] = s

        result = DiscoveryResult(
            pages=pages,
            actions=all_actions,
            personas=personas,
            capabilities=list(unique_caps.values()),
            states=list(unique_states.values()),
            invariants=invariants,
            goals=goals,
            coverage_map=self.crawler.coverage_map,
            warnings=self.crawler.warnings,
            ai_proposals=ai_proposals,
        )
        return result

    async def rediscover(
        self,
        browser_page: Any,
        existing_pages: list[Page],
        since: datetime | None = None,
        changed_files: list[str] | None = None,
    ) -> DiscoveryResult:
        """Incremental re-discovery: re-crawls only stale or source-changed pages."""
        cutoff = since or (datetime.now(timezone.utc) - timedelta(days=7))
        changed_set = set(changed_files or [])

        # Filter pages that need re-discovery
        pages_to_crawl: list[Page] = []
        for p in existing_pages:
            # Stale check
            p_seen = p.last_seen_at
            if p_seen.tzinfo is None:
                p_seen = p_seen.replace(tzinfo=timezone.utc)
            is_stale = p_seen < cutoff
            # Source file change check
            has_source_changes = bool(set(p.source_files) & changed_set) if changed_set else False

            if is_stale or has_source_changes:
                pages_to_crawl.append(p)

        logger.info(
            "Incremental re-discovery: re-crawling %d of %d pages",
            len(pages_to_crawl),
            len(existing_pages),
        )

        updated_actions: list[Action] = []
        updated_caps: list[Capability] = []
        updated_states: list[State] = []
        ai_proposals: list[AIProposal] = []

        for page in pages_to_crawl:
            try:
                target_url = (self.base_url + page.url_pattern).rstrip("/")
                await browser_page.goto(target_url, wait_until="domcontentloaded", timeout=10000)
                page.last_seen_at = datetime.now(timezone.utc)

                await self.auth_detector.inspect_page_auth(browser_page, page)
                actions, caps, states = await self.capability_extractor.extract_actions_and_capabilities(
                    browser_page, page
                )
                proposals = await self.ai_assistant.assist_ambiguous_actions(
                    actions, {"url": page.url_pattern}
                )

                ai_proposals.extend(proposals)
                updated_actions.extend(actions)
                updated_caps.extend(caps)
                updated_states.extend(states)
            except Exception as e:
                logger.warning("Incremental crawl failed on %s: %s", page.url_pattern, e)

        return DiscoveryResult(
            pages=pages_to_crawl,
            actions=updated_actions,
            capabilities=updated_caps,
            states=updated_states,
            ai_proposals=ai_proposals,
        )
