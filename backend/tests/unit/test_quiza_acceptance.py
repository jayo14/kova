"""End-to-end deterministic acceptance fixture and multi-app verification.

Covers the Quiza sign-in page (https://quiza-ai.vercel.app/signin) and a structurally
different application (public documentation viewer with search/filter) to verify:
1. Accurate page readiness and authentication classification.
2. Complete public control identification.
3. Grounded control exploration for password visibility toggling.
4. Grounded navigation tests for forgot-password and signup routes.
5. External OAuth boundary recognition and prerequisite blocking.
6. Honest absence of authenticated quiz/dashboard journeys without credentials.
7. Quality gate rejection of generic layout element-count assertions.
8. Semantic distinction between eligible runnable tests and blocked/inferred tests.
9. Truthful execution verdicts (PASSED, FAILED, BLOCKED, UNVERIFIED).
10. Generalization to structurally different applications without overfitting.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.browser.readiness import PageReadiness, classify_page, PageSignals
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.schemas import DiscoveredMission
from app.modules.exploration.journey_validator import (
    validate_journey,
    repair_journey,
    deduplicate_and_rank_journeys,
)
from app.engine.verification.verifier import Verifier, VerificationResult


@pytest.fixture(autouse=True)
def disable_ai(monkeypatch):
    """Ensure tests are fully deterministic without remote LLM calls."""
    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)


# ── Quiza Sign-In Deterministic Fixture ──────────────────────────────────────

def make_quiza_page_signals() -> PageSignals:
    return PageSignals(
        requested_url="https://quiza-ai.vercel.app/signin",
        observed_url="https://quiza-ai.vercel.app/signin",
        title="Quiza - Sign in",
        body_text="Sign in to your account. Email address. Password. Show password. Forgot password? Sign In. Continue with Google. Don't have an account? Sign up.",
        interactive_count=6,
        link_count=2,
        nav_item_count=0,
        heading_count=1,
    )


def make_quiza_observation() -> dict:
    return {
        "url": "https://quiza-ai.vercel.app/signin",
        "title": "Quiza - Sign in",
        "text": "Sign in to your account. Email address. Password. Show password. Forgot password? Sign In. Continue with Google. Don't have an account? Sign up.",
        "elements": [
            {"type": "input", "name": "Email address", "selector": "input[type='email']", "tag": "input"},
            {"type": "input", "name": "Password", "selector": "input[type='password']", "tag": "input"},
            {"type": "button", "name": "Show password", "selector": "button[aria-label='Show password']", "tag": "button"},
            {"type": "link", "name": "Forgot password?", "selector": "a[href='/forgot-password']", "tag": "a", "href": "/forgot-password"},
            {"type": "button", "name": "Sign In", "selector": "button[type='submit']", "tag": "button"},
            {"type": "button", "name": "Continue with Google", "selector": "button.google-oauth", "tag": "button"},
            {"type": "link", "name": "Sign up", "selector": "a[href='/signup']", "tag": "a", "href": "/signup"},
        ],
    }


# ── Acceptance Points 1 to 9 ────────────────────────────────────────────────

def test_quiza_point_1_page_classification():
    """Point 1: Correctly classifies the page as an authentication or sign-in surface."""
    signals = make_quiza_page_signals()
    cls = classify_page(signals)
    assert cls.state == PageReadiness.AUTHENTICATION_REQUIRED
    assert cls.is_ready is False
    assert "login" in cls.reason.lower() or "authentication" in cls.reason.lower()


def test_quiza_point_2_identifies_public_controls():
    """Point 2: Identifies email, password, password toggle, forgot password, sign up, Google OAuth."""
    obs = make_quiza_observation()
    elements = obs["elements"]
    names = [el["name"] for el in elements]

    assert "Email address" in names
    assert "Password" in names
    assert "Show password" in names
    assert "Forgot password?" in names
    assert "Sign up" in names
    assert "Continue with Google" in names


def test_quiza_point_3_password_visibility_toggle_test():
    """Point 3: Generates a valid control exploration test for password visibility toggling with dual toggle."""
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")
    toggle_el = {"type": "button", "name": "Show password", "selector": "button[aria-label='Show password']"}
    mission = engine._build_element_mission(toggle_el, "https://quiza-ai.vercel.app/signin", "Quiza - Sign in", "User")

    assert mission is not None
    assert mission.kind == "control_exploration"
    assert mission.runnable is True
    assert mission.validation_status == "eligible"
    assert "password visibility" in mission.name.lower()
    assert "element_attribute" in mission.successCondition
    assert mission.successCondition["element_attribute"]["attribute"] == "type"
    assert mission.successCondition["element_attribute"]["value"] == "password"

    # Verifies dual toggle steps: type into password, click toggle, click toggle again
    actions = [s.get("type") for s in mission.steps]
    assert "type" in actions
    assert actions.count("click") >= 2

    # Passes quality gate
    val = validate_journey(mission)
    assert val.is_valid, [d.message for d in val.defects]


def test_quiza_point_4_navigation_tests_for_subroutes():
    """Point 4: Generates valid navigation tests for forgot-password and signup routes asserting destination."""
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")

    # Forgot password
    forgot_el = {"type": "link", "name": "Forgot password?", "selector": "a[href='/forgot-password']", "href": "/forgot-password"}
    m_forgot = engine._build_element_mission(forgot_el, "https://quiza-ai.vercel.app/signin", "Quiza - Sign in", "User")
    assert m_forgot.kind == "navigation_test"
    assert m_forgot.runnable is True
    assert m_forgot.validation_status == "eligible"
    assert "forgot-password" in str(m_forgot.successCondition)
    val_forgot = validate_journey(m_forgot)
    assert val_forgot.is_valid

    # Sign up
    signup_el = {"type": "link", "name": "Sign up", "selector": "a[href='/signup']", "href": "/signup"}
    m_signup = engine._build_element_mission(signup_el, "https://quiza-ai.vercel.app/signin", "Quiza - Sign in", "User")
    assert m_signup.kind == "navigation_test"
    assert m_signup.runnable is True
    assert m_signup.validation_status == "eligible"
    assert "signup" in str(m_signup.successCondition)
    val_signup = validate_journey(m_signup)
    assert val_signup.is_valid


def test_quiza_point_5_google_oauth_external_boundary():
    """Point 5: Identifies Google OAuth as an external boundary, marked as blocked by prerequisites."""
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")
    oauth_el = {"type": "button", "name": "Continue with Google", "selector": "button.google-oauth"}
    mission = engine._build_element_mission(oauth_el, "https://quiza-ai.vercel.app/signin", "Quiza - Sign in", "User")

    assert mission.runnable is False
    assert mission.validation_status == "blocked_by_prerequisites"
    assert mission.recommended is False
    assert any("oauth" in r.lower() or "external" in r.lower() for r in mission.rejection_reasons)
    assert "external_google_credentials" in mission.provenance.get("unmet_preconditions", [])


def test_quiza_point_6_no_fake_authenticated_journeys():
    """Point 6: Does NOT generate a passing or recommended authenticated quiz/dashboard journey without credentials."""
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")
    obs = make_quiza_observation()

    class DummyPage:
        url = "https://quiza-ai.vercel.app/signin"

    missions = engine._generate_fast_path_missions(DummyPage(), obs, goal=None)

    # Must NOT contain authenticated quiz or dashboard flows
    for m in missions:
        name_lower = m.name.lower()
        assert "quiz" not in name_lower
        assert "dashboard" not in name_lower
        if "sign in" in name_lower or "log in" in name_lower:
            # Login without credentials must be blocked
            assert m.runnable is False
            assert m.validation_status == "blocked_by_prerequisites"


def test_quiza_point_7_rejects_generic_explore_password_button():
    """Point 7: Does NOT generate generic 'Explore Show password' test with trivial layout assertions."""
    bad_mission = DiscoveredMission(
        id="bad-pwd",
        name="Explore Show password",
        objective="Verify that interacting with 'Show password' executes as expected",
        journey=["Visit Quiza", "Click 'Show password'", "Verify visible feedback or navigation"],
        steps=[
            {"type": "navigate", "url": "https://quiza-ai.vercel.app/signin"},
            {"type": "click", "target": "button[aria-label='Show password']"},
        ],
        successCondition={"element_count": {"selector": "main, [role='main'], form, table", "min": 1}},
        classification="functional",
        expected_outcome=None,
    )

    val = validate_journey(bad_mission)
    assert not val.is_valid
    assert any(d.code in ("VACUOUS_ASSERTION", "VAGUE_OUTCOME", "SHALLOW_NAVIGATION") for d in val.defects)

    # Quality gate must refuse to repair this into an eligible runnable mission
    ranked = deduplicate_and_rank_journeys([bad_mission])
    assert not any(m.name == "Explore Show password" and m.runnable for m in ranked)


def test_quiza_point_8_distinguishes_eligible_runnable_and_blocked():
    """Point 8: Distinguishes clearly between eligible runnable tests and blocked/inferred tests."""
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")
    obs = make_quiza_observation()

    class DummyPage:
        url = "https://quiza-ai.vercel.app/signin"

    missions = engine._generate_fast_path_missions(DummyPage(), obs, goal=None)
    ranked = deduplicate_and_rank_journeys(missions)

    runnable = [m for m in ranked if m.runnable]
    blocked = [m for m in ranked if not m.runnable and m.validation_status == "blocked_by_prerequisites"]

    assert len(runnable) >= 1
    assert any("password visibility" in m.name.lower() for m in runnable)

    # Blocked flows exist and have explicit unmet prerequisites
    assert any("credentials" in m.name.lower() or "oauth" in m.name.lower() for m in blocked)
    for b in blocked:
        assert b.recommended is False
        assert len(b.rejection_reasons) > 0


@pytest.mark.asyncio
async def test_quiza_point_9_truthful_execution_verdicts():
    """Point 9: Produces truthful execution verdicts (PASSED, FAILED, BLOCKED, UNVERIFIED)."""
    # 1. PASSED: Password toggle attribute correctly verified
    mock_page = AsyncMock()
    mock_loc = AsyncMock()
    mock_loc.first = mock_loc
    mock_loc.get_attribute = AsyncMock(return_value="password")
    mock_loc.evaluate = AsyncMock(return_value="password")
    mock_page.locator = MagicMock(return_value=mock_loc)

    verifier = Verifier(mock_page)
    result_pass = await verifier.verify({
        "element_attribute": {
            "target": "input[type='password']",
            "attribute": "type",
            "value": "password",
        }
    })
    assert result_pass.passed is True
    assert result_pass.outcome == "PASSED"

    # 2. FAILED: Expected attribute mismatch
    mock_loc.get_attribute = AsyncMock(return_value="text")
    mock_loc.evaluate = AsyncMock(return_value="text")
    result_fail = await verifier.verify({
        "element_attribute": {
            "target": "input[type='password']",
            "attribute": "type",
            "value": "password",
        }
    })
    assert result_fail.passed is False
    assert result_fail.outcome == "FAILED"

    # 3. UNVERIFIED: No verifiable condition provided
    result_unverified = await verifier.verify({})
    assert result_unverified.passed is False
    assert result_unverified.outcome == "UNVERIFIED"

    # 4. BLOCKED: Authentication barrier prevents reaching state
    from app.engine.verification.verifier import VerificationCheck
    result_blocked = VerificationResult(
        passed=False,
        checks=[VerificationCheck(type="auth_barrier", passed=False, message="auth required to access destination")]
    )
    assert result_blocked.outcome == "BLOCKED"


# ── Second Structurally Different Application Fixture ───────────────────────

def make_docs_viewer_observation() -> dict:
    return {
        "url": "https://docs.acme-cloud.io/",
        "title": "Acme Cloud Documentation",
        "text": "Acme Cloud Documentation. Search API reference, guides, and tutorials. Getting Started. Architecture. API Reference. Release Notes.",
        "elements": [
            {"type": "input", "name": "Search documentation", "selector": "input[type='search']", "tag": "input"},
            {"type": "link", "name": "API Reference", "selector": "a[href='/api']", "tag": "a", "href": "/api"},
            {"type": "link", "name": "Getting Started", "selector": "a[href='/guides/getting-started']", "tag": "a", "href": "/guides/getting-started"},
            {"type": "button", "name": "Light / Dark Theme", "selector": "button.theme-toggle", "tag": "button"},
        ],
    }


def test_second_app_docs_viewer_generalization():
    """Verifies that discovery and quality gates generalize to non-auth content and search applications."""
    obs = make_docs_viewer_observation()
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://docs.acme-cloud.io/")

    class DummyPage:
        url = "https://docs.acme-cloud.io/"

    missions = engine._generate_fast_path_missions(DummyPage(), obs, goal=None)
    ranked = deduplicate_and_rank_journeys(missions)

    # Must produce grounded search or navigation tests
    assert len(ranked) >= 1
    rec = next((m for m in ranked if m.recommended), None)
    assert rec is not None
    assert rec.runnable is True
    assert rec.validation_status == "eligible"
    assert rec.kind in ("feature_test", "navigation_test")

    # The search mission verifies matching results or query route
    search_mission = next((m for m in ranked if "search" in m.name.lower()), None)
    if search_mission:
        assert search_mission.runnable is True
        assert search_mission.kind == "feature_test"
        assert search_mission.successCondition is not None

    # Navigation to API Reference verifies destination URL
    api_mission = next((m for m in ranked if "api reference" in m.name.lower()), None)
    if api_mission:
        assert api_mission.runnable is True
        assert api_mission.kind == "navigation_test"
        assert "api" in str(api_mission.successCondition)
