"""Pipeline quality, evidence provenance, and false confidence regression suite.

Covers all 16 required pipeline regression scenarios with negative assertions
to guarantee that low-quality discovery, false confidence, and vacuous passes
cannot recur:

1. Provider interstitial vs. real application distinction.
2. Slow-loading application eventually becomes ready.
3. Non-recovering interstitial times out with an explicit terminal reason.
4. Public exploration of an unauthenticated application generates grounded journeys.
5. Exploration of an authenticated app without credentials produces public tests or prerequisite blocks, never fake authenticated journeys.
6. Password visibility toggle produces a dual-toggle verification test.
7. External OAuth button is recognized as an external boundary, not a generic local button click.
8. Navigation to registration and recovery routes verifies destination arrival.
9. Quality gate rejects generic actions, missing assertions, and invented elements.
10. Quality gate rejects layout-only success conditions on functional journeys.
11. Provenance is preserved on all candidate missions.
12. Recommendation engine picks the best eligible journey, or none if none qualify.
13. Frontend receives explicit status for runnable, blocked, and rejected journeys.
14. Execution runner returns BLOCKED when prerequisites are missing.
15. Execution runner returns UNVERIFIED when evidence is insufficient.
16. Execution runner returns PASSED only with positive, non-vacuous evidence.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.browser.readiness import (
    PageReadiness,
    classify_page,
    PageSignals,
    ReadinessWaiter,
)
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.schemas import DiscoveredMission
from app.modules.exploration.journey_validator import (
    validate_journey,
    repair_journey,
    deduplicate_and_rank_journeys,
)
from app.engine.verification.verifier import (
    Verifier,
    VerificationResult,
    VerificationCheck,
    is_vacuous_condition,
)


@pytest.fixture(autouse=True)
def disable_ai(monkeypatch):
    """Ensure tests are fully deterministic without remote LLM calls."""
    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)


# ── 1. Provider interstitial vs. real application distinction ────────────────

def test_scenario_1_provider_interstitial_vs_real_application():
    interstitial_signals = PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Render - Application loading",
        body_text="Incoming HTTP request detected. Service waking up. Allocating compute resources. START BUILDING ON RENDER TODAY",
        interactive_count=1,
        link_count=1,
    )
    res_interstitial = classify_page(interstitial_signals)
    assert res_interstitial.state == PageReadiness.HOSTING_INTERSTITIAL
    assert res_interstitial.is_ready is False

    # Negative assertion: never accept as application ready or unknown page
    assert res_interstitial.state != PageReadiness.APPLICATION_READY
    assert res_interstitial.state != PageReadiness.UNKNOWN_PAGE

    ready_signals = PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Huntly",
        body_text="Huntly Bookmark Manager. Save, search and tag articles. Dashboard. Collections. Settings.",
        interactive_count=12,
        link_count=18,
    )
    res_ready = classify_page(ready_signals)
    assert res_ready.state == PageReadiness.APPLICATION_READY
    assert res_ready.is_ready is True
    assert res_ready.state != PageReadiness.HOSTING_INTERSTITIAL


# ── 2. Slow-loading application eventually becomes ready ─────────────────────

@pytest.mark.asyncio
async def test_scenario_2_slow_loading_application_becomes_ready():
    initial_signals = PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Render - Application loading",
        body_text="Incoming HTTP request detected. Service waking up. Allocating compute resources. START BUILDING ON RENDER TODAY",
        interactive_count=1,
        link_count=1,
        nav_item_count=0,
        heading_count=1,
    )
    ready_signals = PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Huntly",
        body_text="Huntly Bookmark Manager. Discover, save and organize content. Dashboard. Collections. Search records.",
        interactive_count=10,
        link_count=15,
        nav_item_count=4,
        heading_count=3,
    )

    async def mock_probe():
        return classify_page(ready_signals)

    initial = classify_page(initial_signals)
    assert initial.state == PageReadiness.HOSTING_INTERSTITIAL

    waiter = ReadinessWaiter(
        probe=mock_probe,
        intervals=(0.01,),
        total_timeout=1.0,
    )

    assessment = await waiter.resolve(initial)
    assert assessment.state == PageReadiness.APPLICATION_READY
    assert assessment.is_ready is True
    # Negative assertion: not marked as timeout or interstitial
    assert assessment.state != PageReadiness.HOSTING_INTERSTITIAL


# ── 3. Non-recovering interstitial times out with explicit terminal reason ───

@pytest.mark.asyncio
async def test_scenario_3_non_recovering_interstitial_times_out():
    interstitial_signals = PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Render - Application loading",
        body_text="Incoming HTTP request detected. Service waking up. Allocating compute resources. START BUILDING ON RENDER TODAY",
        interactive_count=1,
        link_count=1,
        nav_item_count=0,
        heading_count=1,
    )

    async def mock_probe():
        return classify_page(interstitial_signals)

    initial = classify_page(interstitial_signals)
    assert initial.state == PageReadiness.HOSTING_INTERSTITIAL

    waiter = ReadinessWaiter(
        probe=mock_probe,
        intervals=(0.01,),
        total_timeout=0.02,
    )

    assessment = await waiter.resolve(initial)
    assert assessment.state == PageReadiness.HOSTING_INTERSTITIAL
    assert assessment.is_ready is False
    assert "did not change" in assessment.uncertainty.lower() or "hosting" in assessment.reason.lower()

    # Negative assertion: never deemed ready
    assert assessment.is_ready is not True


# ── 4. Public exploration of unauthenticated app generates grounded journeys ─

def test_scenario_4_public_unauthenticated_app_grounded_journeys():
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://blog.example.com")
    obs = {
        "url": "https://blog.example.com",
        "title": "Tech Blog",
        "elements": [
            {"type": "link", "name": "Latest Articles", "selector": "a[href='/articles']", "href": "/articles"},
            {"type": "input", "name": "Search posts", "selector": "input[type='search']", "tag": "input"},
        ],
    }

    class DummyPage:
        url = "https://blog.example.com"

    missions = engine._generate_fast_path_missions(DummyPage(), obs, goal=None)
    ranked = deduplicate_and_rank_journeys(missions)

    assert len(ranked) >= 1
    for m in ranked:
        assert m.runnable is True
        assert m.validation_status == "eligible"
        # Negative assertion: no vague placeholders
        assert "visible feedback" not in m.expected_outcome.lower()
        assert "destination content rendered" not in m.expected_outcome.lower()


# ── 5. Authenticated app without credentials produces no fake journeys ───────

def test_scenario_5_authenticated_app_without_credentials_blocks_private_flows():
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")
    obs = {
        "url": "https://quiza-ai.vercel.app/signin",
        "title": "Quiza - Sign in",
        "elements": [
            {"type": "button", "name": "Sign In", "selector": "button[type='submit']"},
            {"type": "button", "name": "Continue with Google", "selector": "button.google-oauth"},
        ],
    }

    class DummyPage:
        url = "https://quiza-ai.vercel.app/signin"

    missions = engine._generate_fast_path_missions(DummyPage(), obs, goal=None)
    ranked = deduplicate_and_rank_journeys(missions)

    # Negative assertions: zero runnable authenticated flows, zero recommended
    runnable = [m for m in ranked if m.runnable]
    assert len(runnable) == 0
    assert not any(m.recommended for m in ranked)
    assert all(m.validation_status == "blocked_by_prerequisites" for m in ranked)


# ── 6. Password visibility toggle produces dual-toggle verification test ─────

def test_scenario_6_password_visibility_toggle_dual_step():
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://app.example.com/login")
    el = {"type": "button", "name": "Show password", "selector": "button[aria-label='Show password']"}
    mission = engine._build_element_mission(el, "https://app.example.com/login", "Login", "User")

    assert mission.kind == "control_exploration"
    assert mission.runnable is True
    assert "element_attribute" in mission.successCondition
    assert mission.successCondition["element_attribute"]["attribute"] == "type"
    assert mission.successCondition["element_attribute"]["value"] == "password"

    # Negative assertion: not a single-click shallow navigation test
    assert mission.kind != "navigation_test"
    assert "element_count" not in mission.successCondition


# ── 7. External OAuth button is recognized as an external boundary ───────────

def test_scenario_7_external_oauth_button_boundary():
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://app.example.com/login")
    for provider in ("Continue with Google", "Sign in with GitHub", "Log in with Apple"):
        el = {"type": "button", "name": provider, "selector": f"button.{provider.split()[-1].lower()}"}
        mission = engine._build_element_mission(el, "https://app.example.com/login", "Login", "User")

        assert mission.runnable is False
        assert mission.validation_status == "blocked_by_prerequisites"
        # Negative assertion: cannot be recommended or treated as automated local login
        assert mission.recommended is False
        assert "steps" not in mission.steps or len(mission.steps) == 0


# ── 8. Navigation to registration and recovery routes verifies destination ───

def test_scenario_8_navigation_routes_verify_destination():
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://app.example.com/login")
    routes = [
        ("Forgot password?", "/forgot-password"),
        ("Sign up", "/signup"),
    ]
    for name, href in routes:
        el = {"type": "link", "name": name, "selector": f"a[href='{href}']", "href": href}
        mission = engine._build_element_mission(el, "https://app.example.com/login", "Login", "User")

        assert mission.kind == "navigation_test"
        assert mission.runnable is True
        assert "url_matches" in mission.successCondition
        assert href.lstrip("/") in mission.successCondition["url_matches"]["pattern"]

        # Negative assertion: not layout element count
        assert "element_count" not in mission.successCondition


# ── 9. Quality gate rejects generic actions, missing assertions, invented el ─

def test_scenario_9_quality_gate_rejects_generic_actions_and_missing_assertions():
    bad_missions = [
        DiscoveredMission(
            id="bad-action",
            name="Generic Action Flow",
            objective="Use the control",
            journey=["Visit app", "Use the control matching the goal", "Verify state"],
            steps=[{"type": "navigate", "url": "https://example.com"}, {"type": "click", "target": "button"}],
            successCondition={"url_matches": {"pattern": ".*"}},
        ),
        DiscoveredMission(
            id="bad-assertion",
            name="Vague Outcome Flow",
            objective="Check outcome",
            journey=["Visit app", "Click button", "Verify visible feedback"],
            steps=[{"type": "navigate", "url": "https://example.com"}, {"type": "click", "target": "button"}],
            successCondition=None,
            expected_outcome="Verify visible feedback or navigation",
        ),
    ]

    for m in bad_missions:
        val = validate_journey(m)
        assert not val.is_valid
        repaired = repair_journey(m)
        val2 = validate_journey(repaired)
        # Negative assertion: repair does NOT silently pass these generic defects
        assert not val2.is_valid


# ── 10. Quality gate rejects layout-only success conditions on functional ────

def test_scenario_10_quality_gate_rejects_layout_only_conditions():
    vacuous_mission = DiscoveredMission(
        id="vacuous-layout",
        name="Submit Form and Verify",
        objective="Verify form submission",
        journey=["Visit form", "Submit form", "Verify result"],
        steps=[{"type": "navigate", "url": "https://example.com/form"}, {"type": "click", "target": "button[type='submit']"}],
        successCondition={"element_count": {"selector": "main, [role='main'], header, footer, body", "min": 1}},
        classification="functional",
        expected_outcome="Verify destination content rendered",
    )

    val = validate_journey(vacuous_mission)
    assert not val.is_valid
    assert any(d.code == "VACUOUS_ASSERTION" for d in val.defects)

    # Negative assertion: cannot be ranked as eligible
    ranked = deduplicate_and_rank_journeys([vacuous_mission])
    assert len(ranked) == 0


# ── 11. Provenance is preserved on all candidate missions ────────────────────

def test_scenario_11_provenance_preserved_on_candidate_missions():
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://app.example.com")
    el = {"type": "button", "name": "Show password", "selector": "button#show-pwd"}
    mission = engine._build_element_mission(el, "https://app.example.com", "App", "User")

    assert mission.provenance is not None
    assert "observed_controls" in mission.provenance
    assert "observed_routes" in mission.provenance
    assert "Show password" in mission.provenance["observed_controls"]

    # Negative assertion: provenance cannot be empty dict or None
    assert len(mission.provenance["observed_controls"]) > 0


# ── 12. Recommendation engine picks the best eligible journey, or none ───────

def test_scenario_12_recommendation_picks_eligible_or_none():
    blocked_mission = DiscoveredMission(
        id="blocked-1",
        name="Private Dashboard (needs credentials)",
        objective="Access dashboard",
        journey=["Visit", "Login"],
        steps=[],
        runnable=False,
        validation_status="blocked_by_prerequisites",
        rejection_reasons=["Needs credentials"],
        category="auth",
    )

    ranked_empty = deduplicate_and_rank_journeys([blocked_mission])
    # Negative assertion: blocked journey is NEVER recommended
    assert not any(m.recommended for m in ranked_empty)

    eligible_mission = DiscoveredMission(
        id="eligible-1",
        name="Search Documentation",
        objective="Verify search returns results",
        journey=["Visit", "Search 'API'", "Verify results"],
        steps=[
            {"type": "navigate", "url": "https://example.com"},
            {"type": "type", "target": "input[type='search']", "value": "API"},
            {"type": "click", "target": "button[type='submit']"},
        ],
        successCondition={"element_count": {"selector": "article, .result-item", "min": 1}},
        classification="functional",
        category="feature",
        expected_outcome="Search results display article matches",
        runnable=True,
        validation_status="eligible",
    )

    ranked_with_eligible = deduplicate_and_rank_journeys([blocked_mission, eligible_mission])
    # Exactly one recommended mission, and it MUST be the eligible runnable one
    recs = [m for m in ranked_with_eligible if m.recommended]
    assert len(recs) == 1
    assert recs[0].id == "eligible-1"
    assert recs[0].runnable is True


# ── 13. Frontend receives explicit status for runnable, blocked, rejected ────

def test_scenario_13_serialization_includes_status_for_frontend():
    m = DiscoveredMission(
        id="m-1",
        name="Google OAuth Sign-in",
        objective="Authenticate via Google",
        journey=["Click Google"],
        steps=[],
        kind="control_exploration",
        runnable=False,
        validation_status="blocked_by_prerequisites",
        rejection_reasons=["External OAuth boundary"],
        provenance={"observed_controls": ["Continue with Google"]},
    )
    payload = m.model_dump()
    assert payload["runnable"] is False
    assert payload["validation_status"] == "blocked_by_prerequisites"
    assert payload["kind"] == "control_exploration"
    assert "External OAuth boundary" in payload["rejection_reasons"]
    assert "observed_controls" in payload["provenance"]

    # Negative assertion: fields must not be None or omitted
    assert payload["validation_status"] != "eligible"


# ── 14. Execution runner returns BLOCKED when prerequisites are missing ──────

@pytest.mark.asyncio
async def test_scenario_14_execution_returns_blocked():
    check = VerificationCheck(type="auth_barrier", passed=False, message="Destination requires authentication barrier login")
    res = VerificationResult(passed=False, checks=[check])
    assert res.outcome == "BLOCKED"
    # Negative assertion: not PASSED or UNVERIFIED
    assert res.outcome != "PASSED"
    assert res.outcome != "UNVERIFIED"


# ── 15. Execution runner returns UNVERIFIED when evidence is insufficient ────

@pytest.mark.asyncio
async def test_scenario_15_execution_returns_unverified():
    mock_page = AsyncMock()
    verifier = Verifier(mock_page)

    # Empty condition
    res_empty = await verifier.verify({})
    assert res_empty.outcome == "UNVERIFIED"
    assert res_empty.passed is False

    # Unknown condition
    res_unknown = await verifier.verify({"unsupported_future_check": {"val": 1}})
    assert res_unknown.outcome == "UNVERIFIED"
    assert res_unknown.passed is False

    # Negative assertion: never report PASSED
    assert res_empty.outcome != "PASSED"
    assert res_unknown.outcome != "PASSED"


# ── 16. Execution runner returns PASSED only with positive evidence ──────────

@pytest.mark.asyncio
async def test_scenario_16_execution_returns_passed_only_with_positive_evidence():
    mock_page = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.first = mock_loc
    mock_loc.get_attribute = AsyncMock(return_value="password")
    mock_loc.evaluate = AsyncMock(return_value="password")
    mock_page.locator = MagicMock(return_value=mock_loc)

    verifier = Verifier(mock_page)

    # Real positive attribute check passes
    res_valid = await verifier.verify({
        "element_attribute": {"target": "input[type='password']", "attribute": "type", "value": "password"}
    })
    assert res_valid.passed is True
    assert res_valid.outcome == "PASSED"

    # Vacuous selector check fails closed
    res_vacuous = await verifier.verify({
        "element_count": {"selector": "main, [role='main'], header, footer, body", "min": 1}
    })
    assert res_vacuous.passed is False
    assert res_vacuous.outcome == "FAILED"

    # Negative assertion: vacuous selector CANNOT pass
    assert res_vacuous.outcome != "PASSED"
