"""Evaluation and regression suite for purposeful user journey synthesis (Tier B).

Validates:
1. Heuristic cleanup: Skip links, same-page anchors, and site taglines are never
   emitted as journeys or objectives.
2. AI failure fallback: When AI synthesis fails, emits
   'AI planning unavailable: showing basic page checks only' with basic check classification.
3. Synthesis input: Rich SiteMap with key section text (pricing plans, product lists,
   form fields) and page summaries feed journey synthesis.
4. Generic capability checklist: Journeys proposed for evidence-supported categories.
5. Repair loop: Actually runs and grounds weak candidate outcomes.
6. Tier B recall: Dripp produces >=5 concrete journeys, Huntly >=4 concrete journeys,
   with no skip links or anchors, and successful AI synthesis logs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
import pytest
import yaml

from app.engine.ai.provider import AIProvider, TaskType
from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import AIGeneratedJourney, AIGeneratedJourneyList
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.journey_validator import (
    deduplicate_and_rank_journeys,
    repair_journey,
    validate_journey,
)
from app.modules.exploration.schemas import DiscoveredMission


class RealisticTierBAIEngine(AIProvider):
    """AI Provider simulating structured journey synthesis grounded in observed DOM evidence."""

    def __init__(self, site_type: str = "generic"):
        super().__init__()
        self.site_type = site_type
        self.calls: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return "mock-model"

    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type,
        task_type: TaskType = TaskType.GENERAL,
        **kwargs: Any,
    ) -> Any:
        self.calls.append({
            "system_prompt": system,
            "user_prompt": prompt,
            "task_type": task_type,
        })

        if schema == AIGeneratedJourneyList:
            if self.site_type == "dripp":
                # E-commerce coffee platform
                journeys = [
                    AIGeneratedJourney(
                        name="Browse product list",
                        title="Browse Products",
                        description="Explore coffee catalog and observe product cards with pricing.",
                        objective="Verify that visitor can browse coffee blends and see product prices",
                        category="feature",
                        kind="read_workflow",
                        journey=["Open store", "Browse product catalog", "Verify product items render"],
                        steps=[
                            {"type": "navigate", "url": "https://dripp.demo/"},
                            {"type": "click", "target": "Catalog"},
                        ],
                        expected_outcome="Product list displays coffee items with names, roast types, and prices ($18-$22).",
                        evidence_refs=["section:products", "button:Catalog", "item:Cold Brew Blend"],
                        control_hints=["Catalog", "Products"],
                        recommended=True,
                        confidence=0.95,
                    ),
                    AIGeneratedJourney(
                        name="Open product detail",
                        title="View Product",
                        description="Select a coffee product to view detailed notes and brewing guide.",
                        objective="Verify that selecting a product opens its detail view with specifications",
                        category="feature",
                        kind="read_workflow",
                        journey=["Open store", "Click on Cold Brew Blend", "Verify detail sheet displays"],
                        steps=[
                            {"type": "navigate", "url": "https://dripp.demo/"},
                            {"type": "click", "target": "Cold Brew Blend"},
                        ],
                        expected_outcome="Product detail view displays roast profile, origin notes, and Add to Cart action.",
                        evidence_refs=["item:Cold Brew Blend", "button:View Details"],
                        control_hints=["Cold Brew Blend", "View Details"],
                        confidence=0.92,
                    ),
                    AIGeneratedJourney(
                        name="Add to cart",
                        title="Add to Cart",
                        description="Add a bag of coffee to the shopping cart and verify cart count updates.",
                        objective="Verify that clicking Add to Cart adds item and updates cart indicator",
                        category="feature",
                        kind="write_workflow",
                        journey=["Open product", "Click Add to Cart", "Verify cart badge updates"],
                        steps=[
                            {"type": "navigate", "url": "https://dripp.demo/"},
                            {"type": "click", "target": "Add to Cart"},
                        ],
                        expected_outcome="Cart drawer opens showing 1 item with subtotal and active checkout action.",
                        evidence_refs=["button:Add to Cart", "drawer:cart"],
                        control_hints=["Add to Cart"],
                        confidence=0.94,
                    ),
                    AIGeneratedJourney(
                        name="View cart",
                        title="View Cart",
                        description="Open shopping cart drawer to review order summary.",
                        objective="Verify customer can inspect items, quantities, and subtotal in the cart",
                        category="feature",
                        kind="read_workflow",
                        journey=["Open store", "Click Cart button", "Verify cart summary"],
                        steps=[
                            {"type": "navigate", "url": "https://dripp.demo/"},
                            {"type": "click", "target": "View Cart"},
                        ],
                        expected_outcome="Cart slideout displays itemized list, quantity adjustment buttons, and subtotal.",
                        evidence_refs=["button:View Cart", "drawer:cart"],
                        control_hints=["View Cart"],
                        confidence=0.90,
                    ),
                    AIGeneratedJourney(
                        name="Start checkout",
                        title="Start Checkout",
                        description="Initiate checkout sequence from the cart to begin order entry.",
                        objective="Verify that clicking checkout starts payment/shipping flow",
                        category="feature",
                        kind="write_workflow",
                        journey=["Open cart", "Click Checkout", "Verify checkout modal or view renders"],
                        steps=[
                            {"type": "navigate", "url": "https://dripp.demo/"},
                            {"type": "click", "target": "Checkout"},
                        ],
                        expected_outcome="Checkout view loads with shipping address fields and payment summary.",
                        evidence_refs=["button:Checkout", "form:checkout"],
                        control_hints=["Checkout"],
                        confidence=0.91,
                    ),
                    AIGeneratedJourney(
                        name="Contact form validation",
                        title="Contact Form Validation",
                        description="Test contact form validation when submitting empty or valid inquiries.",
                        objective="Verify contact form validates inputs and displays submission confirmation",
                        category="form",
                        kind="write_workflow",
                        journey=["Open contact", "Fill name, email, message", "Click Send"],
                        steps=[
                            {"type": "navigate", "url": "https://dripp.demo/"},
                            {"type": "fill", "target": "Name", "value": "Test User"},
                            {"type": "fill", "target": "Email", "value": "test@dripp.demo"},
                            {"type": "fill", "target": "Message", "value": "Wholesale inquiry"},
                            {"type": "click", "target": "Send Message"},
                        ],
                        expected_outcome="Contact form submits and displays thank you notification.",
                        evidence_refs=["form:contact", "input:Email", "button:Send Message"],
                        control_hints=["Send Message"],
                        confidence=0.88,
                    ),
                ]
                return AIGeneratedJourneyList(
                    journeys=journeys,
                    recommendation_reason="Dripp is an e-commerce coffee brand; recommending Browse Products as the core customer journey.",
                )

            elif self.site_type == "huntly":
                # SaaS knowledge & bookmarking workspace
                journeys = [
                    AIGeneratedJourney(
                        name="Signup validation",
                        title="Signup Validation",
                        description="Verify registration form fields and validation feedback on missing inputs.",
                        objective="Verify user registration form validates email and password constraints",
                        category="auth",
                        kind="write_workflow",
                        journey=["Open signup", "Submit without password", "Verify error indicator"],
                        steps=[
                            {"type": "navigate", "url": "https://huntly-0pgj.onrender.com/signup"},
                            {"type": "fill", "target": "Email", "value": "newuser@huntly.demo"},
                            {"type": "click", "target": "Create Account"},
                        ],
                        expected_outcome="Registration form highlights missing password field with error notice.",
                        evidence_refs=["form:signup", "input:Email", "button:Create Account"],
                        control_hints=["Create Account"],
                        confidence=0.91,
                    ),
                    AIGeneratedJourney(
                        name="Login with wrong credentials",
                        title="Login Error Validation",
                        description="Attempt authentication with invalid credentials and verify error alert.",
                        objective="Verify login form rejects invalid credentials and renders warning banner",
                        category="auth",
                        kind="write_workflow",
                        journey=["Open login", "Fill bad credentials", "Click Sign In", "Verify error alert"],
                        steps=[
                            {"type": "navigate", "url": "https://huntly-0pgj.onrender.com/login"},
                            {"type": "fill", "target": "Email", "value": "wrong@huntly.demo"},
                            {"type": "fill", "target": "Password", "value": "badpassword123"},
                            {"type": "click", "target": "Sign In"},
                        ],
                        expected_outcome="Authentication fails and displays alert: 'Invalid email or password'.",
                        evidence_refs=["form:login", "input:Email", "button:Sign In"],
                        control_hints=["Sign In"],
                        confidence=0.93,
                    ),
                    AIGeneratedJourney(
                        name="'Get started' leads to signup",
                        title="Get Started Entrance",
                        description="Click Get Started on landing hero and verify redirection to registration view.",
                        objective="Verify landing page Get Started button navigates directly to user onboarding",
                        category="feature",
                        kind="navigation",
                        journey=["Open landing", "Click Get Started", "Verify /signup route loaded"],
                        steps=[
                            {"type": "navigate", "url": "https://huntly-0pgj.onrender.com/"},
                            {"type": "click", "target": "Get Started"},
                        ],
                        expected_outcome="Browser navigates to signup view with registration form rendered.",
                        evidence_refs=["button:Get Started", "route:/signup"],
                        control_hints=["Get Started"],
                        confidence=0.95,
                        recommended=True,
                    ),
                    AIGeneratedJourney(
                        name="Pricing plans visible with functional buttons",
                        title="Pricing Plans & Selection",
                        description="Review subscription tiers and verify selection buttons trigger checkout or signup.",
                        objective="Verify pricing tiers display features, monthly rates, and selectable plan buttons",
                        category="feature",
                        kind="read_workflow",
                        journey=["Open pricing", "Compare Starter, Pro, Enterprise", "Click Select Plan"],
                        steps=[
                            {"type": "navigate", "url": "https://huntly-0pgj.onrender.com/"},
                            {"type": "click", "target": "Pricing"},
                        ],
                        expected_outcome="Pricing comparison matrix displays Starter ($0), Pro ($29), and Enterprise ($99) with active selection buttons.",
                        evidence_refs=["section:pricing", "button:Select Plan", "heading:Pricing Plans"],
                        control_hints=["Pricing", "Select Plan"],
                        confidence=0.92,
                    ),
                ]
                return AIGeneratedJourneyList(
                    journeys=journeys,
                    recommendation_reason="Huntly is a knowledge curation SaaS; recommending Get Started entrance and onboarding.",
                )

        raise ValueError(f"Unsupported schema in mock: {schema}")


def test_tier_b_public_yml_contains_labeled_dripp_and_huntly():
    """Verify labeled Tier B entries exist in tier_b_public.yml."""
    yml_path = Path(__file__).parents[2] / "benchmarks" / "fixtures" / "tier_b_public.yml"
    assert yml_path.exists(), f"{yml_path} must exist"
    entries = yaml.safe_load(yml_path.read_text(encoding="utf-8"))

    dripp = next((e for e in entries if e.get("id") == "dripp"), None)
    assert dripp is not None, "Dripp entry must exist in tier_b_public.yml"
    assert dripp.get("acceptance_minimum_journeys") >= 5
    assert "browse a product list" in dripp.get("labeled_expected_journeys", [])
    assert "add to cart" in dripp.get("labeled_expected_journeys", [])
    assert "start checkout" in dripp.get("labeled_expected_journeys", [])

    huntly = next((e for e in entries if e.get("id") == "huntly"), None)
    assert huntly is not None, "Huntly entry must exist in tier_b_public.yml"
    assert huntly.get("acceptance_minimum_journeys") >= 4
    assert "signup validation" in huntly.get("labeled_expected_journeys", [])
    assert "login with wrong credentials" in huntly.get("labeled_expected_journeys", [])


@pytest.mark.asyncio
async def test_dripp_synthesis_acceptance_produces_at_least_5_concrete_journeys():
    """Acceptance: Dripp produces >=5 journeys with concrete outcomes; none is a skip link or anchor."""
    provider = RealisticTierBAIEngine(site_type="dripp")
    reasoner = AgentReasoner(provider)

    site_map = [
        {
            "url": "https://dripp.demo/",
            "title": "Dripp Coffee & Cold Brew",
            "needs_auth": False,
            "forms": [
                {
                    "name": "contact",
                    "action": "/contact",
                    "inputs": [
                        {"name": "name", "type": "text", "required": True},
                        {"name": "email", "type": "email", "required": True},
                        {"name": "message", "type": "textarea", "required": True},
                    ],
                }
            ],
            "primary_actions": [
                {"name": "Add to Cart", "type": "button"},
                {"name": "View Cart", "type": "button"},
                {"name": "Checkout", "type": "button"},
            ],
            "interactive_elements": [
                {"name": "Skip to main content", "type": "a", "href": "#main-content"},  # skip link
                {"name": "Solution", "type": "a", "href": "#solution"},  # same-page anchor
                {"name": "Pricing", "type": "a", "href": "#pricing"},  # same-page anchor
                {"name": "Cold Brew Blend", "type": "a", "href": "/products/cold-brew"},
                {"name": "Add to Cart", "type": "button"},
                {"name": "View Cart", "type": "button"},
                {"name": "Checkout", "type": "button"},
                {"name": "Send Message", "type": "button"},
            ],
            "key_sections": [
                {
                    "type": "products",
                    "name": "Coffee Catalog",
                    "items": ["Cold Brew Blend - $18", "Espresso Roast - $20", "Ethiopia Yirgacheffe - $22"],
                }
            ],
            "page_summary": "Dripp artisan coffee roasters. Browse our single origin beans and craft cold brew blends.",
        }
    ]

    result = await reasoner.synthesize_journeys(
        base_url="https://dripp.demo/",
        title="Dripp Coffee",
        goal=None,
        persona="Shopper",
        site_map=site_map,
        max_journeys=7,
    )

    assert result is not None
    assert len(result.journeys) >= 5, f"Expected >=5 journeys for Dripp, got {len(result.journeys)}"

    # Check that generic capability checklist is present in system prompt
    assert len(provider.calls) > 0
    sys_prompt = provider.calls[0]["system_prompt"]
    assert "GENERIC CAPABILITY CHECKLIST" in sys_prompt
    assert "Signup and login validation" in sys_prompt
    assert "Add to cart and checkout start" in sys_prompt
    assert "NEVER treat skip links" in sys_prompt
    assert "NEVER treat same-page anchors" in sys_prompt

    # Check journey quality constraints
    for j in result.journeys:
        # None is a skip link or anchor
        name_lower = j.name.lower()
        obj_lower = j.objective.lower()
        assert "skip to" not in name_lower and "skip to" not in obj_lower
        assert "#solution" not in name_lower and "#pricing" not in name_lower
        assert "#main-content" not in name_lower
        assert "verify core journeys for:" not in name_lower

        # Concrete outcome required
        assert j.expected_outcome and len(j.expected_outcome) >= 15
        assert "verify visible feedback" not in j.expected_outcome.lower()

        # Evidence refs required
        assert len(j.evidence_refs) > 0, f"Journey '{j.name}' must have evidence refs"


@pytest.mark.asyncio
async def test_huntly_synthesis_acceptance_produces_at_least_4_concrete_journeys():
    """Acceptance: Huntly produces >=4 journeys with concrete outcomes; none is a skip link or anchor."""
    provider = RealisticTierBAIEngine(site_type="huntly")
    reasoner = AgentReasoner(provider)

    site_map = [
        {
            "url": "https://huntly-0pgj.onrender.com/",
            "title": "Huntly - Bookmark & Knowledge Workspace",
            "needs_auth": False,
            "forms": [
                {
                    "name": "login",
                    "action": "/login",
                    "inputs": [
                        {"name": "email", "type": "email", "required": True},
                        {"name": "password", "type": "password", "required": True},
                    ],
                },
                {
                    "name": "signup",
                    "action": "/signup",
                    "inputs": [
                        {"name": "email", "type": "email", "required": True},
                        {"name": "password", "type": "password", "required": True},
                    ],
                },
            ],
            "primary_actions": [
                {"name": "Get Started", "type": "a", "href": "/signup"},
                {"name": "Sign In", "type": "button"},
                {"name": "Select Plan", "type": "button"},
            ],
            "interactive_elements": [
                {"name": "Skip to main content", "type": "a", "href": "#main-content"},
                {"name": "Features", "type": "a", "href": "#features"},
                {"name": "Get Started", "type": "a", "href": "/signup"},
                {"name": "Sign In", "type": "button"},
                {"name": "Select Plan", "type": "button"},
            ],
            "key_sections": [
                {
                    "type": "pricing",
                    "name": "Pricing & Plans",
                    "items": ["Starter - $0/mo", "Pro - $29/mo", "Enterprise - $99/mo"],
                }
            ],
            "page_summary": "Huntly helps knowledge workers discover, save, and organize articles and web research.",
        }
    ]

    result = await reasoner.synthesize_journeys(
        base_url="https://huntly-0pgj.onrender.com/",
        title="Huntly",
        goal=None,
        persona="Researcher",
        site_map=site_map,
        max_journeys=6,
    )

    assert result is not None
    assert len(result.journeys) >= 4, f"Expected >=4 journeys for Huntly, got {len(result.journeys)}"

    for j in result.journeys:
        name_lower = j.name.lower()
        obj_lower = j.objective.lower()
        assert "skip to" not in name_lower and "skip to" not in obj_lower
        assert "#features" not in name_lower and "#main-content" not in name_lower
        assert "verify core journeys for:" not in name_lower

        assert j.expected_outcome and len(j.expected_outcome) >= 15
        assert len(j.evidence_refs) > 0


def test_validator_rejects_skip_links_same_page_anchors_and_taglines():
    """Verify validator flags skip links, # anchors, and marketing taglines."""
    # 1. Skip link
    skip_mission = DiscoveredMission(
        id="m-skip",
        name="Navigate to Skip to main content",
        title="Skip to content",
        description="Skip navigation to content",
        objective="Verify that user can navigate to Skip to main content",
        steps=[{"type": "click", "target": "#main-content"}],
        expected_outcome="User navigates to main content container",
        classification="navigation",
        kind="navigation",
    )
    val_skip = validate_journey(skip_mission)
    assert not val_skip.is_valid
    assert any(d.code == "SKIP_LINK_OR_ANCHOR" for d in val_skip.defects)

    # 2. Same-page anchor
    anchor_mission = DiscoveredMission(
        id="m-anchor",
        name="Navigate to #solution",
        title="Solution section",
        description="Jump to solution anchor",
        objective="Verify that user jumps to #solution anchor",
        route_analysis={"path": "#solution"},
        steps=[{"type": "click", "target": "#solution"}],
        expected_outcome="Scroll down to solution section",
        classification="navigation",
        kind="navigation",
    )
    val_anchor = validate_journey(anchor_mission)
    assert not val_anchor.is_valid
    assert any(d.code == "SAME_PAGE_ANCHOR" for d in val_anchor.defects)

    # 3. Tagline mission
    tagline_mission = DiscoveredMission(
        id="m-tagline",
        name="Verify core journeys for: The all-in-one AI platform for modern teams",
        title="All in one platform",
        description="Verify core journeys",
        objective="Verify core journeys for: The all-in-one AI platform for modern teams",
        steps=[{"type": "navigate", "url": "https://example.com"}],
        expected_outcome="Platform loads successfully",
        classification="navigation",
        kind="navigation",
    )
    val_tagline = validate_journey(tagline_mission)
    assert not val_tagline.is_valid
    assert any(d.code == "TAGLINE_MISSION" for d in val_tagline.defects)


def test_repair_loop_repairs_weak_outcomes():
    """Verify that Prompt 16 repair loop executes and repairs weak outcomes."""
    weak_cart_mission = DiscoveredMission(
        id="m-cart",
        name="Add product to cart and checkout",
        title="Add to Cart",
        description="Customer adds an item to cart and checks out",
        objective="Verify customer can add item to cart and proceed",
        steps=[
            {"type": "navigate", "url": "https://dripp.demo/"},
            {"type": "click", "target": "Add to Cart"},
            {"type": "click", "target": "Checkout"},
        ],
        expected_outcome="",  # missing / vague outcome
        classification="functional",
        kind="write_workflow",
    )

    repaired = repair_journey(weak_cart_mission)
    assert repaired.expected_outcome != ""
    assert "cart" in repaired.expected_outcome.lower()
    assert repaired.repaired is True

    val = validate_journey(repaired)
    assert val.is_valid, f"Repaired mission should now be valid, defects: {[d.message for d in val.defects]}"


@pytest.mark.asyncio
async def test_ai_failure_fallback_message_and_basic_check_classification():
    """Verify that when AI synthesis fails, UI message is set and results classified as basic checks."""
    class FailingAIProvider(AIProvider):
        def __init__(self):
            super().__init__()

        @property
        def model_name(self) -> str:
            return "failing-model"

        async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Model synthesis service unavailable")

    explorer = ExplorationEngine(exploration_id="exp-test", url="https://example.com", project_id=None)
    explorer._page_alive = True
    emitted_events = []

    async def mock_emit(ev_type: str, data: dict):
        emitted_events.append({"type": ev_type, "data": data})

    explorer._emit = mock_emit

    # Mock page with interactive controls
    class MockPage:
        url = "https://example.com"
        async def evaluate(self, script: str):
            return []

    observation = {
        "url": "https://example.com",
        "title": "Example App",
        "elements": [
            {"name": "Dashboard", "type": "a", "href": "/dashboard"},
            {"name": "Settings", "type": "a", "href": "/settings"},
            {"name": "Help Center", "type": "a", "href": "/docs"},
        ],
        "forms": [],
        "headings": ["Welcome to Example App"],
        "text": "Example application dashboard and settings.",
    }

    # Monkeypatch AI provider to use failing provider
    import app.engine.exploration.explorer as exp_mod
    original_get_provider = exp_mod.get_ai_provider
    exp_mod.get_ai_provider = lambda: FailingAIProvider()

    try:
        discoveries, missions = await explorer._discover_workflows(MockPage(), observation, selected_role="User")

        # Check emitted event
        fail_ev = next((ev for ev in emitted_events if ev["type"] == "ai_synthesis_failed"), None)
        assert fail_ev is not None, "ai_synthesis_failed event must be emitted"
        assert fail_ev["data"]["message"] == "AI planning unavailable: showing basic page checks only"

        # Check that recommendation also conveys fallback
        rec = explorer._generate_recommendation(missions)
        assert rec == "AI planning unavailable: showing basic page checks only"

        # Check classification of resulting checks
        assert len(missions) > 0
        for m in missions:
            assert m.classification == "basic_check"
            assert m.expectation_source == "heuristic_fallback"
    finally:
        exp_mod.get_ai_provider = original_get_provider
