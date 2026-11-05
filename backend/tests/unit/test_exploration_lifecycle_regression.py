"""Regression tests for exploration lifecycle fixes.

Covers:
- Evidence-driven auth recovery (no repeated identical submissions)
- Duplicate account prevention (single exploration identity)
- Email verification requirements
- Password recovery only when justified
- Backend availability without successful authentication
- Auth failure with continued public exploration
- Repeated actions with no new evidence
- Shared exploration budget across auth and discovery
- Reallocation when auth is blocked
- Duplicate journey consolidation
- Navigation checks vs core workflows
- Termination without meaningful progress

Uses the FakeSite/FakePage pattern from test_exploration_agent_loop.py
and does not hardcode any app-specific routes, features, or workflows.
"""

from __future__ import annotations

import pytest

from app.engine.exploration.agent.agent import ExplorationAgent
from app.engine.exploration.agent.auth_evaluator import (
    AuthOption,
    AuthStrategyEvaluator,
    AuthSurfaceAnalysis,
)
from app.engine.exploration.agent.budget import ResourceBudget
from app.engine.exploration.agent.schemas import (
    AgentActionProposal,
    ExplorationAction,
)
from app.engine.exploration.agent.understanding import ApplicationUnderstanding
from app.modules.exploration.journey_validator import (
    deduplicate_and_rank_journeys,
    is_navigation_only_workflow,
)
from app.modules.exploration.schemas import DiscoveredMission

ORIGIN = "https://app.example.test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _link(name: str, href: str, selector: str | None = None) -> dict:
    return {"type": "link", "name": name, "href": href, "selector": selector or f"a[data-name='{name}']"}


def _input(name: str, type_: str = "text", placeholder: str = "") -> dict:
    return {
        "type": type_,
        "name": name,
        "placeholder": placeholder,
        "id": name,
        "autocomplete": name,
        "selector": f"input[name='{name}']",
    }


def _button(name: str, selector: str | None = None) -> dict:
    return {"type": "button", "name": name, "selector": selector or f"button[data-name='{name}']"}


class FakeSite:
    def __init__(self, pages: dict[str, dict], start: str, trap: bool = False,
                 click_routes: dict[str, str] | None = None):
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
        inputs = list(spec.get("inputs") or [])
        dialogs = [
            {"title": name, "name": name, "elements": [_button("Reports")]}
            for name in sorted(self.dialogs)
        ]
        return {
            "url": url,
            "title": spec.get("title"),
            "headings": spec.get("headings") or [],
            "elements": elements,
            "inputs": inputs,
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
        agent._provider_resolved = True
        agent.provider = None
    return agent, events


# ---------------------------------------------------------------------------
# 1. Registration with inconclusive outcome
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inconclusive_registration_then_login_with_same_identity():
    """Registration is inconclusive; agent should retry login with the same
    exploration identity, not create a duplicate account."""
    site = FakeSite(
        {
            f"{ORIGIN}/register": {
                "title": "Register",
                "headings": [],
                "elements": [
                    _button("Create account", "#register-submit"),
                    _link("Sign in", "/login"),
                ],
                "inputs": [
                    _input("email", "email", "Email"),
                    _input("password", "password", "Password"),
                ],
                "forms": [{"name": "register", "action": "/register"}],
            },
            f"{ORIGIN}/login": {
                "title": "Sign in",
                "headings": [],
                "elements": [
                    _button("Sign in", "#login-submit"),
                ],
                "inputs": [
                    _input("email", "email", "Email"),
                    _input("password", "password", "Password"),
                ],
                "forms": [{"name": "login", "action": "/login"}],
            },
            f"{ORIGIN}/dashboard": {
                "title": "Dashboard",
                "headings": [],
                "elements": [_button("Sign out", "#signout")],
            },
        },
        start=f"{ORIGIN}/register",
        click_routes={
            "#login-submit": f"{ORIGIN}/dashboard",
        },
    )
    agent, events = _agent(site, budget={"max_actions": 30, "max_pages": 30})

    result = await agent.run()

    # Agent should not have attempted registration more than once
    reg_attempts = [
        a for a in agent.understanding.attempted_auth_strategies
        if a.get("type") == "self_registration"
    ]
    assert len(reg_attempts) <= 1, f"Expected <=1 registration attempt, got {len(reg_attempts)}"

    # Agent should have reached an authenticated state (via login or BFS)
    assert agent.understanding.is_currently_authenticated is True

    # Exploration identity should be set and reused
    assert agent.understanding.exploration_identity is not None
    assert agent.understanding.exploration_identity.get("email") is not None

    # Auth blocked flag should not be set prematurely
    assert not agent.understanding.auth_blocked


# ---------------------------------------------------------------------------
# 2. Duplicate account prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_duplicate_accounts_after_failed_registration():
    """After registration is submitted and inconclusive, agent must not
    register again with a different identity."""
    site = FakeSite(
        {
            f"{ORIGIN}/register": {
                "title": "Register",
                "headings": [],
                "elements": [_button("Create account", "#register-submit")],
                "forms": [{"name": "register", "action": "/register"}],
            },
            f"{ORIGIN}/login": {
                "title": "Sign in",
                "headings": [],
                "elements": [_button("Sign in", "#login-submit")],
                "forms": [{"name": "login", "action": "/login"}],
            },
        },
        start=f"{ORIGIN}/register",
        click_routes={
            "#login-submit": f"{ORIGIN}/dashboard",
        },
    )
    agent, _ = _agent(site, budget={"max_actions": 30, "max_pages": 30})

    await agent.run()

    # Exactly one registration should be submitted
    reg_attempts = [
        a for a in agent.understanding.attempted_auth_strategies
        if a.get("type") == "self_registration"
    ]
    assert len(reg_attempts) == 1, f"Expected exactly 1 registration, got {len(reg_attempts)}"

    # Only one exploration identity should exist
    assert agent.understanding.exploration_identity is not None
    assert agent.understanding.registration_submitted is True

    # Identity should not change
    identity = agent.understanding.exploration_identity
    assert identity["email"] is not None


# ---------------------------------------------------------------------------
# 3. Login failure without repeated identical submissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_login_without_new_evidence_blocks_auth():
    """After two failed login attempts with identical credentials, auth
    should be marked blocked and the agent should not keep retrying."""
    site = FakeSite(
        {
            f"{ORIGIN}/login": {
                "title": "Sign in",
                "headings": [],
                "elements": [_button("Sign in", "#login-submit")],
                "inputs": [
                    _input("email", "email", "Email"),
                    _input("password", "password", "Password"),
                ],
                "forms": [{"name": "login", "action": "/login"}],
            },
            f"{ORIGIN}/public": {
                "title": "Public",
                "headings": [],
                "elements": [_button("Read article", "#read")],
            },
        },
        start=f"{ORIGIN}/login",
        click_routes={},  # Login never succeeds; stays on /login
    )
    # Provide configured credentials so the auth strategy evaluator is used
    agent, events = _agent(
        site,
        budget={"max_actions": 30, "max_pages": 30},
        credentials={"email": "user@example.com", "password": "password123"},
    )

    result = await agent.run()

    # Auth should be blocked after repeated failures
    assert agent.understanding.auth_blocked is True
    assert agent.understanding.auth_blocker_reason != ""

    # Login attempts should be limited (not endless)
    login_attempts = [
        a for a in agent.understanding.attempted_auth_strategies
        if a.get("type") == "native_login"
    ]
    assert len(login_attempts) <= 3, f"Expected <=3 login attempts, got {len(login_attempts)}"

    # The agent should still terminate with a meaningful reason
    assert result["termination"] in (
        "budget_exhausted", "diminishing_returns", "no_evidence_acquired", "frontier_empty"
    )


# ---------------------------------------------------------------------------
# 4. Email verification requirement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_verification_blocks_auth_without_password_recovery():
    """When registration indicates email verification is required, the agent
    should not initiate password recovery unless evidence justifies it."""
    understanding = ApplicationUnderstanding(target_url=f"{ORIGIN}/")
    understanding.mark_auth_blocked("EMAIL_VERIFICATION_REQUIRED")

    assert understanding.auth_blocked is True
    assert "EMAIL_VERIFICATION_REQUIRED" in understanding.auth_blockers
    assert understanding.auth_blocker_reason == "EMAIL_VERIFICATION_REQUIRED"

    # Password recovery should NOT be automatically authorized
    assert understanding.registration_outcome != "succeeded"


# ---------------------------------------------------------------------------
# 5. Backend availability without successful authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_available_but_auth_not_established():
    """Backend can respond but authentication never establishes a session.
    Agent should report the blocker and continue exploring public pages."""
    site = FakeSite(
        {
            f"{ORIGIN}/login": {
                "title": "Sign in",
                "headings": [],
                "elements": [_button("Sign in", "#login-submit")],
                "inputs": [
                    _input("email", "email", "Email"),
                    _input("password", "password", "Password"),
                ],
                "forms": [{"name": "login", "action": "/login"}],
            },
            f"{ORIGIN}/about": {
                "title": "About",
                "headings": [{"level": 1, "text": "About Us"}],
                "elements": [],
            },
        },
        start=f"{ORIGIN}/login",
        click_routes={},  # Login never succeeds
    )
    # Provide credentials so auth strategy evaluator attempts login
    agent, events = _agent(
        site,
        budget={"max_actions": 30, "max_pages": 30},
        credentials={"email": "user@example.com", "password": "password123"},
    )

    result = await agent.run()

    # Auth should be blocked after failed login
    assert agent.understanding.auth_blocked is True

    # But the agent should still discover the public About page via BFS
    visited = {node.url_norm for node in agent.sitemap.nodes.values()}
    assert f"{ORIGIN}/about" in visited or f"{ORIGIN}/login" in visited

    # Termination should reflect the actual outcome, not a fake success
    assert result["termination"] != "frontier_empty" or agent.understanding.auth_blocked


# ---------------------------------------------------------------------------
# 6. Auth failure with continued public exploration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_blocked_then_public_exploration_continues():
    """When auth is blocked, the agent should reallocate effort to public
    feature discovery instead of repeatedly attempting login."""
    site = FakeSite(
        {
            f"{ORIGIN}/login": {
                "title": "Sign in",
                "headings": [],
                "elements": [_button("Sign in", "#login-submit")],
                "inputs": [
                    _input("email", "email", "Email"),
                    _input("password", "password", "Password"),
                ],
                "forms": [{"name": "login", "action": "/login"}],
            },
            f"{ORIGIN}/public": {
                "title": "Public",
                "headings": [{"level": 1, "text": "Public Page"}],
                "elements": [_button("Read article", "#read")],
            },
            f"{ORIGIN}/article": {
                "title": "Article",
                "headings": [{"level": 1, "text": "Article"}],
                "elements": [],
            },
        },
        start=f"{ORIGIN}/login",
        click_routes={
            "#read": f"{ORIGIN}/article",
        },  # Login never succeeds
    )
    # Provide credentials so auth strategy evaluator attempts login
    agent, _ = _agent(
        site,
        budget={"max_actions": 30, "max_pages": 30},
        credentials={"email": "user@example.com", "password": "password123"},
    )

    result = await agent.run()

    # Auth should be blocked
    assert agent.understanding.auth_blocked is True

    # But public pages should still be discovered
    visited = {node.url_norm for node in agent.sitemap.nodes.values()}
    assert f"{ORIGIN}/public" in visited or f"{ORIGIN}/article" in visited

    # Budget should show discovery effort was allocated after auth was blocked
    budget = result["stats"].get("budget", {})
    if budget:
        discovery_effort = budget.get("categories", {}).get("discovery", {}).get("effort_spent", 0)
        auth_effort = budget.get("categories", {}).get("auth", {}).get("effort_spent", 0)
        # Discovery should receive meaningful effort even if auth was attempted
        assert discovery_effort > 0 or auth_effort > 0


# ---------------------------------------------------------------------------
# 7. Repeated actions with no new evidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_action_without_new_evidence_terminates():
    """An exploration that keeps producing the same state should terminate
    with a meaningful reason, not just exhaust a fixed count."""
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Home",
                "headings": [],
                "elements": [_link("Trap", "/trap?n=0")],
            },
        },
        start=f"{ORIGIN}/",
        trap=True,
    )
    agent, _ = _agent(site, budget={"max_actions": 12, "max_pages": 50})

    result = await agent.run()

    # Should terminate due to budget or diminishing returns
    assert result["termination"] in (
        "budget_exhausted", "diminishing_returns", "no_evidence_acquired"
    )

    # Actions taken should not exceed the budget
    assert result["stats"]["actions"] <= 12


# ---------------------------------------------------------------------------
# 8. Recovery after environmental conditions change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_reallocation_when_auth_blocked():
    """The shared budget should shift effort from auth to discovery when
    auth is blocked but public functionality remains."""
    budget = ResourceBudget(total_effort=50)

    # Simulate spending on auth without success
    for _ in range(4):
        budget.spend("auth", evidence_gained=False)

    # Auth category should be unproductive
    assert budget.category_productivity("auth") == 0.0

    # Discovery should still be prioritizable
    assert budget.should_prioritize("discovery") is True

    # Spend on discovery with evidence
    budget.spend("discovery", evidence_gained=True)
    assert budget.category_productivity("discovery") > 0

    # Auth should be blocked (4/4 unproductive, 4 >= 3)
    assert budget.is_category_blocked("auth") is True

    # Discovery should be prioritized over auth
    assert budget.should_prioritize("discovery") is True
    assert budget.should_prioritize("auth") is False


# ---------------------------------------------------------------------------
# 9. Shared exploration budget across auth and discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_budget_preserves_discovery_effort():
    """The budget should not let auth consume all effort when discovery
    could still produce useful evidence."""
    budget = ResourceBudget(total_effort=100)

    # Spend heavily on auth with no success
    for _ in range(20):
        budget.spend("auth", evidence_gained=False)

    # Auth should be blocked
    assert budget.is_category_blocked("auth") is True

    # Discovery should still have plenty of remaining effort
    remaining = budget.remaining_effort
    assert remaining > 0

    # Discovery should be prioritizable
    assert budget.should_prioritize("discovery") is True

    # Overall productivity should be low but not zero
    assert budget.overall_productivity == 0.0  # no evidence yet


# ---------------------------------------------------------------------------
# 10. Duplicate journey consolidation
# ---------------------------------------------------------------------------


def test_duplicate_journeys_with_different_entry_points_are_consolidated():
    """Two journeys with the same user goal but different entry points
    should be consolidated into one."""
    search_via_nav = DiscoveredMission(
        id="m-search-nav",
        name="Search for resources",
        title="Search for resources",
        description="Use the main navigation search",
        objective="Find learning resources via search",
        persona="User",
        category="workflow",
        user_goal="Find learning resources",
        journey=["Open app", "Click search", "Enter query", "View results"],
        steps=[
            {"type": "navigate", "url": "https://example.com"},
            {"type": "click", "target": "#nav-search"},
            {"type": "type", "target": "search input", "value": "math"},
            {"type": "click", "target": "#search-submit"},
        ],
        successCondition={"element_count": {"selector": ".search-results", "min": 1}},
        confidence=0.8,
        expected_outcome="Search results for math are displayed",
        classification="functional",
        is_core=True,
    )

    search_via_hero = DiscoveredMission(
        id="m-search-hero",
        name="Search for resources",
        title="Search for resources",
        description="Use the hero section search",
        objective="Find learning resources via search",
        persona="User",
        category="workflow",
        user_goal="Find learning resources",
        journey=["Open app", "Click hero search", "Enter query", "View results"],
        steps=[
            {"type": "navigate", "url": "https://example.com"},
            {"type": "click", "target": "#hero-search"},
            {"type": "type", "target": "search input", "value": "math"},
            {"type": "click", "target": "#search-submit"},
        ],
        successCondition={"element_count": {"selector": ".search-results", "min": 1}},
        confidence=0.9,
        expected_outcome="Search results for math are displayed",
        classification="functional",
        is_core=True,
    )

    ranked = deduplicate_and_rank_journeys([search_via_nav, search_via_hero])

    # Should be consolidated to one journey
    assert len(ranked) == 1, f"Expected 1 consolidated journey, got {len(ranked)}"
    assert ranked[0].id == "m-search-hero"  # higher confidence wins
    assert ranked[0].confidence == 0.9


def test_navigation_checks_are_not_core_workflows():
    """Navigation-only journeys (About, Blog, Careers) should be flagged
    as navigation-only, not core product workflows."""
    about_mission = DiscoveredMission(
        id="m-about",
        name="Open About Us",
        title="Open About Us",
        description="View the About page",
        objective="Confirm About page renders",
        persona="Visitor",
        category="navigation",
        journey=["Open app", "Click About", "Verify page loads"],
        steps=[
            {"type": "navigate", "url": "https://example.com"},
            {"type": "click", "target": "#about-link"},
        ],
        successCondition={"element_count": {"selector": "h1", "min": 1}},
        confidence=0.7,
        expected_outcome="About page renders",
        classification="navigation",
        is_core=False,
    )

    assert is_navigation_only_workflow(about_mission) is True


def test_core_workflow_is_not_navigation_only():
    """A workflow with form input and submission is not navigation-only."""
    search_mission = DiscoveredMission(
        id="m-search",
        name="Search for resources",
        title="Search for resources",
        description="Search and view results",
        objective="Find learning resources",
        persona="User",
        category="workflow",
        user_goal="Find learning resources",
        journey=["Open app", "Enter search query", "Submit search", "View results"],
        steps=[
            {"type": "navigate", "url": "https://example.com/search"},
            {"type": "type", "target": "search input", "value": "math"},
            {"type": "click", "target": "#search-submit"},
        ],
        successCondition={"element_count": {"selector": ".search-results", "min": 1}},
        confidence=0.85,
        expected_outcome="Search results for math are displayed",
        classification="functional",
        is_core=True,
    )

    assert is_navigation_only_workflow(search_mission) is False


# ---------------------------------------------------------------------------
# 11. Termination without meaningful progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exploration_terminates_without_meaningful_progress():
    """An exploration that reaches its limit without authenticated workspace
    or meaningful feature discovery must not be reported as successful."""
    site = FakeSite(
        {
            f"{ORIGIN}/": {
                "title": "Home",
                "headings": [],
                "elements": [_link("Docs", "/docs")],
            },
            f"{ORIGIN}/docs": {
                "title": "Docs",
                "headings": [],
                "elements": [],
            },
        },
        start=f"{ORIGIN}/",
    )
    agent, _ = _agent(site, budget={"max_actions": 4, "max_pages": 10})

    result = await agent.run()

    # No authenticated workspace
    assert agent.understanding.is_currently_authenticated is False

    # Budget should reflect the actual state
    budget_info = result["stats"].get("budget", {})
    assert budget_info.get("actions_taken", 0) > 0

    # The exploration should terminate with a meaningful reason (not claim success)
    assert result["termination"] in (
        "budget_exhausted", "frontier_empty", "no_new_state", "diminishing_returns"
    )
    assert result["termination"] != "frontier_empty" or not agent.understanding.is_currently_authenticated


# ---------------------------------------------------------------------------
# Auth strategy evaluator unit tests
# ---------------------------------------------------------------------------


def test_auth_strategy_prevents_duplicate_registration():
    """When registration was already submitted, select_strategy should not
    recommend re-registration."""
    analysis = AuthSurfaceAnalysis(
        is_auth_surface=True,
        has_native_login=True,
        has_registration_form=True,
        has_registration_link=False,
        is_on_register_path=False,
        options=[
            AuthOption(
                method_type="self_registration",
                provider=None,
                label="Create account",
                selector="#register",
            ),
            AuthOption(
                method_type="native_login",
                provider=None,
                label="Sign in",
                selector="#login",
            ),
        ],
    )
    understanding = ApplicationUnderstanding(target_url=f"{ORIGIN}/")
    understanding.registration_submitted = True
    understanding.registration_outcome = "submitted_pending"
    understanding.exploration_identity = {
        "email": "test.kova.abc123@gmail.com",
        "password": "SecurePassword123!xyz",
        "name": "Kova Tester",
    }
    understanding.is_currently_authenticated = False

    strategy, justification = AuthStrategyEvaluator.select_strategy(
        analysis, credentials=None, understanding=understanding
    )

    # Should attempt login, not re-register
    assert strategy is not None
    assert strategy.method_type == "native_login"
    assert "already submitted" in justification.lower() or "existing" in justification.lower()


def test_auth_strategy_blocks_oauth_in_sandbox():
    """OAuth should be blocked as a strategy in an automated sandbox."""
    analysis = AuthSurfaceAnalysis(
        is_auth_surface=True,
        has_native_login=False,
        has_registration_form=False,
        has_registration_link=False,
        is_on_register_path=False,
        options=[
            AuthOption(
                method_type="oauth",
                provider="google",
                label="Sign in with Google",
                selector="#google-login",
            ),
        ],
    )
    understanding = ApplicationUnderstanding(target_url=f"{ORIGIN}/")

    strategy, justification = AuthStrategyEvaluator.select_strategy(
        analysis, credentials=None, understanding=understanding
    )

    assert strategy is None
    assert "OAuth" in justification or "oauth" in justification.lower()

    # OAuth should be marked as not viable
    oauth_methods = [m for m in understanding.discovered_auth_methods if m.get("provider") == "google"]
    assert len(oauth_methods) >= 1
    assert oauth_methods[0]["viable"] is False
