"""Unit tests for the bounded observe -> propose -> act exploration loop.

These use a fake page/engine pair so the loop's determinism, safety policy and
termination behaviour can be asserted without a browser.
"""

from __future__ import annotations

import pytest

from app.engine.exploration.agent.agent import ExplorationAgent
from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction

ORIGIN = "https://app.example.test"


def _link(name: str, href: str, selector: str | None = None) -> dict:
    return {"type": "link", "name": name, "href": href, "selector": selector or f"a[data-name='{name}']"}


def _button(name: str, selector: str | None = None) -> dict:
    return {"type": "button", "name": name, "selector": selector or f"button[data-name='{name}']"}


class FakeSite:
    """A tiny static site keyed by URL, with optional dynamic trap pages."""

    def __init__(
        self,
        pages: dict[str, dict],
        start: str,
        trap: bool = False,
        click_routes: dict[str, str] | None = None,
    ):
        self.pages = pages
        self.start = start
        self.trap = trap
        self.click_routes = click_routes or {}
        self.visits: list[str] = []
        self.clicks: list[str] = []
        self.scrolls = 0
        self.dialogs: set[str] = set()

    def page_for(self, url: str) -> dict:
        if url in self.pages:
            return self.pages[url]
        if self.trap and url.startswith(f"{ORIGIN}/trap"):
            n = int(url.split("n=")[1]) if "n=" in url else 0
            return {
                "title": f"trap {n}",
                "headings": [{"level": 1, "text": f"Trap {n}"}],
                "elements": [_link(f"next-{n + 1}", f"/trap?n={n + 1}")],
            }
        return {"title": "404", "headings": [], "elements": []}

    def observation(self, url: str) -> dict:
        spec = self.page_for(url)
        elements = list(spec.get("elements") or [])
        dialogs = [
            {"title": name, "name": name, "elements": [_button("Reports")]}
            for name in sorted(self.dialogs)
        ]
        return {
            "url": url,
            "title": spec.get("title"),
            "headings": spec.get("headings") or [],
            "elements": elements,
            "forms": spec.get("forms") or [],
            "dialogs": dialogs,
            "alerts": [],
            "routes": [],
        }


class FakeLocator:
    def __init__(self, page: "FakePage", key: str):
        self.page = page
        self.key = key
        self.first = self

    async def is_visible(self, timeout: int = 0) -> bool:
        return True

    async def click(self, timeout: int = 0) -> None:
        self.page.site.clicks.append(self.key)
        route = self.page.site.click_routes.get(self.key)
        if route:
            await self.page.goto(route)
        if self.key.endswith("#menu") or self.key == "Menu":
            self.page.site.dialogs.add("Menu")


class FakePage:
    def __init__(self, site: FakeSite):
        self.site = site
        self.url = site.start
        self.stack: list[str] = []
        self.site.visits.append(self.url)

    async def goto(self, url: str, **kwargs) -> None:
        self.stack.append(self.url)
        self.url = url
        self.site.visits.append(url)

    async def go_back(self, **kwargs):
        if not self.stack:
            return None
        self.url = self.stack.pop()
        self.site.visits.append(self.url)
        return True

    async def evaluate(self, script: str):
        self.site.scrolls += 1
        return None

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def get_by_text(self, text: str, exact: bool = False) -> FakeLocator:
        return FakeLocator(self, str(text))


class FakeEngine:
    def __init__(self, site: FakeSite):
        self.site = site

    async def _observe_current_page(self, page: FakePage) -> dict:
        return self.site.observation(page.url)


class FakeProvider:
    def __init__(self, proposals: list[AgentActionProposal]):
        self.proposals = proposals
        self.calls = 0

    async def generate_structured(self, system: str, prompt: str, schema):
        self.calls += 1
        if not self.proposals:
            return None
        return self.proposals.pop(0)


def _agent(site: FakeSite, **kwargs) -> tuple[ExplorationAgent, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []

    async def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    provider = kwargs.pop("provider", None)
    agent = ExplorationAgent(
        FakeEngine(site),
        FakePage(site),
        emit,
        provider=provider,
        budget=kwargs.pop("budget", None),
    )
    if provider is None:
        # Avoid resolving the real AI provider (and its settings/DB lookup).
        agent._provider_resolved = True
        agent.provider = None
    return agent, events


@pytest.mark.asyncio
async def test_agent_walks_same_origin_links_and_builds_sitemap():
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Home",
                "headings": [{"level": 1, "text": "Home"}],
                "elements": [_link("Docs", "/docs"), _link("Pricing", "/pricing")],
            },
            f"{ORIGIN}/docs": {
                "title": "Docs",
                "headings": [{"level": 1, "text": "Docs"}],
                "elements": [_link("API", "/docs/api")],
            },
            f"{ORIGIN}/pricing": {"title": "Pricing", "headings": [], "elements": []},
            f"{ORIGIN}/docs/api": {"title": "API", "headings": [], "elements": []},
        },
        start=f"{ORIGIN}/",
    )
    agent, events = _agent(site, budget={"max_actions": 20, "max_pages": 20})

    result = await agent.run()

    assert result["termination"] in {"frontier_empty", "budget_exhausted"}
    visited = {node.url_norm for node in agent.sitemap.nodes.values()}
    assert f"{ORIGIN}/docs" in visited
    assert f"{ORIGIN}/pricing" in visited
    assert agent.sitemap.edges, "successful navigations must be recorded as edges"
    assert result["stats"]["actions"] >= 2
    assert any(event == "exploration.agent.act" for event, _ in events)


@pytest.mark.asyncio
async def test_agent_records_but_never_clicks_destructive_controls():
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Account",
                "headings": [],
                "elements": [_button("Settings"), _button("Delete account")],
            },
            f"{ORIGIN}/settings": {"title": "Settings", "headings": [], "elements": []},
        },
        start=f"{ORIGIN}/",
    )
    agent, _ = _agent(site, budget={"max_actions": 10, "max_pages": 10})

    result = await agent.run()

    assert site.clicks, "safe controls should still be clicked"
    assert all("delete" not in click.lower() for click in site.clicks)
    dangerous = result["dangerous_controls"]
    assert [item["name"] for item in dangerous] == ["Delete account"]
    assert dangerous[0]["clicked"] is False


@pytest.mark.asyncio
async def test_agent_ignores_cross_origin_links():
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Home",
                "headings": [],
                "elements": [
                    _link("Docs", "/docs"),
                    _link("External", "https://evil.example.test/steal"),
                ],
            },
            f"{ORIGIN}/docs": {"title": "Docs", "headings": [], "elements": []},
        },
        start=f"{ORIGIN}/",
    )
    agent, _ = _agent(site, budget={"max_actions": 10, "max_pages": 10})

    await agent.run()

    assert all("evil.example.test" not in url for url in site.visits)


@pytest.mark.asyncio
async def test_agent_stops_crawl_trap_within_budget():
    site = FakeSite({f"{ORIGIN}/": {"title": "Home", "headings": [], "elements": []}}, start=f"{ORIGIN}/", trap=True)
    site.pages[f"{ORIGIN}/"] = {
        "title": "Home",
        "headings": [],
        "elements": [_link("Trap", "/trap?n=0")],
    }
    agent, _ = _agent(site, budget={"max_actions": 6, "max_pages": 50})

    result = await agent.run()

    assert result["termination"] == "budget_exhausted"
    assert result["stats"]["actions"] <= 6
    assert len(agent.sitemap.nodes) <= 7


@pytest.mark.asyncio
async def test_agent_uses_valid_ai_proposal():
    site = FakeSite(
        {
            f"{ORIGIN}/": {"title": "Home", "headings": [], "elements": [_link("Docs", "/docs")]},
            f"{ORIGIN}/docs": {"title": "Docs", "headings": [], "elements": []},
        },
        start=f"{ORIGIN}/",
    )
    provider = FakeProvider(
        [
            AgentActionProposal(
                action=ExplorationAction.OPEN_LINK,
                target={"url": f"{ORIGIN}/docs", "text": "Docs"},
                reason="open docs",
                confidence=0.9,
            )
        ]
    )
    agent, events = _agent(site, provider=provider, budget={"max_actions": 4, "max_pages": 4})

    await agent.run()

    sources = [payload.get("source") for event, payload in events if event == "exploration.agent.act"]
    assert "ai" in sources
    assert provider.calls >= 1


@pytest.mark.asyncio
async def test_agent_rejects_hallucinated_ai_target_and_falls_back():
    site = FakeSite(
        {
            f"{ORIGIN}/": {"title": "Home", "headings": [], "elements": [_link("Docs", "/docs")]},
            f"{ORIGIN}/docs": {"title": "Docs", "headings": [], "elements": []},
        },
        start=f"{ORIGIN}/",
    )
    provider = FakeProvider(
        [
            AgentActionProposal(
                action=ExplorationAction.CLICK_CONTROL,
                target={"selector": "#does-not-exist", "text": "Ghost"},
                reason="click ghost",
            )
        ]
    )
    agent, events = _agent(site, provider=provider, budget={"max_actions": 4, "max_pages": 4})

    await agent.run()

    assert any(event == "exploration.agent.reject_proposal" for event, _ in events)
    assert f"{ORIGIN}/docs" in {node.url_norm for node in agent.sitemap.nodes.values()}
    sources = [payload.get("source") for event, payload in events if event == "exploration.agent.act"]
    assert "bfs_fallback" in sources


@pytest.mark.asyncio
async def test_agent_explores_spa_without_links_via_custom_controls():
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Workspace",
                "headings": [],
                "elements": [_button("Open reports", "#openReports")],
            },
            f"{ORIGIN}/reports": {
                "title": "Reports",
                "headings": [{"level": 1, "text": "Reports"}],
                "elements": [],
            },
        },
        start=f"{ORIGIN}/",
        click_routes={"#openReports": f"{ORIGIN}/reports"},
    )
    agent, _ = _agent(site, budget={"max_actions": 6, "max_pages": 10})

    result = await agent.run()

    assert site.clicks == ["#openReports"]
    assert f"{ORIGIN}/reports" in site.visits
    assert result["stats"]["pages"] >= 2
    assert "Open reports" in {cap["name"] for cap in result["capabilities"]}
    assert result["termination"] in ("frontier_empty", "no_new_state")


@pytest.mark.asyncio
async def test_agent_discovers_modal_controls_without_submitting():
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Home",
                "headings": [],
                "elements": [_button("Menu", "#menu")],
            },
        },
        start=f"{ORIGIN}/",
    )
    agent, _ = _agent(site, budget={"max_actions": 6, "max_pages": 10})

    result = await agent.run()

    assert site.clicks == ["#menu"]
    kinds = {(cap["kind"], cap["name"]) for cap in result["capabilities"]}
    assert ("dialog", "Menu") in kinds
    assert all("submit" not in click.lower() for click in site.clicks)
    assert result["termination"] in ("frontier_empty", "no_new_state")
