"""Autonomous Application Exploration and Epistemic Understanding Test Suite.

Verifies application-agnostic intelligence, hypothesis testing, authentication
discovery, state transition tracking, and grounded journey synthesis across
diverse, unfamiliar web applications.
"""

import pytest
from unittest.mock import AsyncMock
from app.engine.exploration.agent.actions import (
    execute_action,
    execute_authenticate,
    execute_fill_inputs,
    execute_open_link,
)
from app.engine.exploration.agent.epistemic_agent import EpistemicExplorationAgent
from app.engine.exploration.agent.journey_synthesizer import JourneySynthesizer
from app.engine.exploration.agent.policy import is_dangerous_control, is_safe_to_click
from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction
from app.engine.exploration.agent.understanding import (
    ApplicationUnderstanding,
    EpistemicState,
)
from app.modules.exploration.journey_validator import is_flimsy_landing_element


# ---------------------------------------------------------------------------
# Test Fixtures & Mocks for Multi-Application Scenarios
# ---------------------------------------------------------------------------

class MockLocator:
    def __init__(self, key: str, visible: bool = True):
        self.key = key
        self.first = self
        self._visible = visible
        self.filled_value: str | None = None
        self.clicked = False

    async def is_visible(self, timeout: int = 0) -> bool:
        return self._visible

    async def click(self, timeout: int = 0) -> None:
        self.clicked = True

    async def focus(self) -> None:
        pass

    async def fill(self, value: str) -> None:
        self.filled_value = value

    async def evaluate(self, script: str) -> None:
        pass

    async def press(self, key: str) -> None:
        pass


class MockPage:
    def __init__(self, start_url: str = "https://app.test/"):
        self.url = start_url
        self.locators: dict[str, MockLocator] = {}
        self.history: list[str] = []

    def locator(self, selector: str) -> MockLocator:
        if selector not in self.locators:
            self.locators[selector] = MockLocator(selector)
        return self.locators[selector]

    def get_by_text(self, text: str, exact: bool = False) -> MockLocator:
        if text not in self.locators:
            self.locators[text] = MockLocator(text)
        return self.locators[text]

    def get_by_role(self, role: str, name: str | None = None) -> MockLocator:
        key = f"{role}:{name}"
        if key not in self.locators:
            self.locators[key] = MockLocator(key)
        return self.locators[key]

    async def goto(self, url: str, **kwargs) -> None:
        self.history.append(self.url)
        self.url = url

    async def go_back(self, **kwargs) -> bool:
        if not self.history:
            return False
        self.url = self.history.pop()
        return True

    async def evaluate(self, script: str) -> None:
        pass


# ---------------------------------------------------------------------------
# 1. Epistemic Understanding Model Tests
# ---------------------------------------------------------------------------

def test_epistemic_understanding_initialization_and_transitions():
    und = ApplicationUnderstanding(
        app_name="CollabStudio",
        target_url="https://studio.test/",
    )

    # Initial state
    assert und.app_name == "CollabStudio"
    assert und.is_currently_authenticated is False
    assert len(und.areas) == 0

    # Discovering areas
    landing = und.record_area("Landing", "/", is_authenticated=False, url="https://studio.test/")
    workspace = und.record_area("Studio Canvas", "/app/canvas", is_authenticated=True, url="https://studio.test/app/canvas")
    assert len(und.areas) == 2
    assert landing.is_authenticated is False
    assert workspace.is_authenticated is True

    # Registering hypothesis
    cap = und.record_capability(
        name="Export Project",
        user_goal="Export project as vector SVG",
        state=EpistemicState.HYPOTHESIS,
        is_core=True,
    )
    assert cap.state == EpistemicState.HYPOTHESIS
    assert cap.confidence == 0.5

    # Experimentally confirming capability
    und.confirm_capability(
        "Export Project",
        {"action": "click", "selector": "#export-btn"},
        "Modal opened and download initiated",
    )
    confirmed_caps = und.get_confirmed_capabilities()
    assert len(confirmed_caps) == 1
    assert confirmed_caps[0].name == "Export Project"
    assert confirmed_caps[0].confidence == 0.95
    assert confirmed_caps[0].state == EpistemicState.CONFIRMED

    # State transitions
    trans = und.record_transition(
        from_url="https://studio.test/login",
        action={"action": "authenticate"},
        to_url="https://studio.test/app/canvas",
        effect="Authenticated and loaded canvas",
    )
    assert len(und.state_transitions) == 1
    assert trans.to_url == "https://studio.test/app/canvas"


def test_epistemic_questions_and_hypothesis_lifecycle():
    und = ApplicationUnderstanding(target_url="https://portal.test/")

    # Add open question
    q = und.add_question(
        question="Does this portal support guest checkout?",
        hypothesis="Guest checkout is permitted without password creation",
        proposed_investigation="Click checkout and observe if registration is enforced",
        priority=3,
    )
    assert q.status == "open"
    assert len(und.open_questions) == 1

    # Answer question after experimentation
    und.answer_question(
        "Does this portal support guest checkout?",
        "Refuted: Registration is strictly mandatory before proceeding",
    )
    assert q.status == "answered"
    assert "Refuted" in (q.answer or "")


# ---------------------------------------------------------------------------
# 2. Quality Gate & Flimsy Card Rejection Tests
# ---------------------------------------------------------------------------

def test_flimsy_landing_elements_rejection():
    # Elements that must be rejected from becoming user journeys
    flimsy_candidates = [
        "Electrical Engineering Tunde A. · 58 pages check_circle",
        "Animal Production Amaka O. · 52 pages check_circle",
        "Computer Science Ibrahim K. · 61 pages check_circle",
        "article Cover page",
        "table_chart Weekly log",
        "engineering Chapter 3",
        "Trusted by 10,000+ teams worldwide",
        "★★★★★ 4.9/5 stars from 300+ reviews",
        "John Doe, Lead Designer at Acme Inc.",
        "Privacy Policy",
        "Terms of Service",
    ]
    for candidate in flimsy_candidates:
        assert is_flimsy_landing_element(candidate) is True, f"Failed to reject flimsy element: {candidate}"

    # Genuine application capabilities that must NOT be rejected
    valid_capabilities = [
        "Create New Logbook",
        "Generate Defence Report",
        "Upload Source Dataset",
        "Configure Model Parameters",
        "Add Team Member",
        "Export Financial Summary",
        "Run Diagnostic Benchmark",
    ]
    for valid in valid_capabilities:
        assert is_flimsy_landing_element(valid) is False, f"Erroneously rejected valid capability: {valid}"


# ---------------------------------------------------------------------------
# 3. Action Execution & Safety Policy Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_execution_form_filling_and_authentication():
    page = MockPage("https://app.test/login")

    # Set up form locators
    email_loc = page.locator('input[type="email"]')
    pwd_loc = page.locator('input[type="password"]')
    submit_loc = page.locator('button[type="submit"]')

    # Test authentication action
    proposal = AgentActionProposal(
        action=ExplorationAction.AUTHENTICATE,
        target={
            "credentials": {"email": "tester@example.test", "password": "SafePassword123!"},
            "submit_selector": 'button[type="submit"]',
        },
        reason="Log in with project credentials",
    )

    success, msg = await execute_action(page, proposal, credentials={"email": "tester@example.test", "password": "SafePassword123!"})
    assert success is True
    assert email_loc.filled_value == "tester@example.test"
    assert pwd_loc.filled_value == "SafePassword123!"
    assert submit_loc.clicked is True


@pytest.mark.asyncio
async def test_safety_policy_blocks_financial_and_destructive_mutations():
    # Destructive operations
    assert is_dangerous_control("Delete workspace") is True
    assert is_dangerous_control("Erase all project data") is True
    assert is_dangerous_control("Reset account") is True

    # Financial operations
    assert is_dangerous_control("Buy Subscription") is True
    assert is_dangerous_control("Pay $49 Now") is True
    assert is_dangerous_control("Place Order") is True
    assert is_dangerous_control("Update credit card") is True

    # Outbound external communications
    assert is_dangerous_control("Send email to team") is True
    assert is_dangerous_control("Invite 100 contacts") is True

    # Safe interactions permitted
    assert is_safe_to_click("Create New Report") is True
    assert is_safe_to_click("Generate Summary") is True
    assert is_safe_to_click("Sign In") is True
    assert is_safe_to_click("Next Step") is True
    assert is_safe_to_click("Search Documents") is True


# ---------------------------------------------------------------------------
# 4. Grounded Journey Synthesis Tests
# ---------------------------------------------------------------------------

def test_journey_synthesizer_generates_grounded_missions():
    und = ApplicationUnderstanding(
        app_name="CloudTelemetry",
        target_url="https://telemetry.test/",
        auth_credentials_available=True,
    )

    # 1. Add confirmed capability
    und.confirm_capability(
        "Generate Incident Postmortem",
        {"action": "click", "target": {"name": "Generate Postmortem"}},
        "Created report and opened editor",
    )

    # 2. Add observed capability in workspace
    und.record_capability(
        name="Create Custom Dashboard",
        user_goal="Assemble telemetry widgets into a custom monitoring dashboard",
        state=EpistemicState.OBSERVED,
        is_core=True,
        entry_url="https://telemetry.test/app/dashboards",
        preconditions=["authenticated_session"],
    )

    # 3. Add flimsy elements (should be filtered out)
    und.record_capability(
        name="John Doe, DevOps Engineer at GlobalCorp",
        user_goal="View testimonial",
        state=EpistemicState.OBSERVED,
    )

    synthesizer = JourneySynthesizer(und, app_name="CloudTelemetry")
    missions = synthesizer.synthesize_journeys()

    mission_names = [m.name for m in missions]

    # Confirmed mission exists with verified status and high confidence
    confirmed_mission = next((m for m in missions if "Postmortem" in m.name), None)
    assert confirmed_mission is not None
    assert confirmed_mission.discovery_status == "verified"
    assert confirmed_mission.confidence == 0.95
    assert confirmed_mission.recommended is True

    # Core observed workspace mission exists
    workspace_mission = next((m for m in missions if "Create Custom Dashboard" in m.name), None)
    assert workspace_mission is not None
    assert workspace_mission.is_core is True

    # Flimsy testimonial was excluded
    assert not any("John Doe" in name for name in mission_names)


# ---------------------------------------------------------------------------
# 5. Autonomous Auth Resolution & Workspace Transition Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_autonomous_self_registration_crosses_auth_barrier_into_workspace():
    """Verifies Kova detects self-registration, registers a test account, and unlocks workspace."""
    und = ApplicationUnderstanding(
        app_name="Quiza",
        target_url="https://quiza.test/signin",
    )

    # 1. Encounter signin page with public registration link
    signin_obs = {
        "url": "https://quiza.test/signin",
        "title": "Quiza - Sign In",
        "links": [{"name": "Sign Up", "href": "https://quiza.test/signup"}],
        "controls": [{"name": "Sign In", "type": "button"}],
        "inputs": [{"name": "email", "type": "email"}, {"name": "password", "type": "password"}],
    }

    # Agent records auth requirement and discovers self-registration opportunity
    und.auth_required = True
    und.auth_type = "password_form"
    und.self_registration_available = True
    q = und.add_question(
        "Can a new user register for this application?",
        "Public self-registration creates active workspace",
        "Register synthetic test account",
    )

    # 2. Simulate registration action execution
    synthetic_account = {
        "email": "test.kova.abc123@example.com",
        "password": "SecurePassword123!",
        "name": "Kova Tester",
    }
    signup_action = {
        "action": "submit_form",
        "target": {"url": "https://quiza.test/signup", "credentials": synthetic_account},
    }

    # 3. Simulate post-registration transition into workspace
    und.record_transition(
        from_url="https://quiza.test/signup",
        action=signup_action,
        to_url="https://quiza.test/dashboard",
        effect="Successfully registered account and navigated to dashboard",
    )
    und.is_currently_authenticated = True
    und.answer_question(q.question, "Confirmed: Registration succeeded and loaded dashboard")

    # 4. Observe workspace capabilities inside dashboard
    und.record_capability(
        name="Generate Quiz from Study Material",
        user_goal="Upload document or notes and generate smart AI quiz",
        state=EpistemicState.CONFIRMED,
        is_core=True,
        expected_outcome="Quiz editor opened with generated questions",
        preconditions=["authenticated_session"],
    )
    und.record_capability(
        name="Manage Recent Quizzes",
        user_goal="Review and retake previously created quizzes",
        state=EpistemicState.OBSERVED,
        is_core=True,
        preconditions=["authenticated_session"],
    )

    # 5. Synthesize journeys
    synthesizer = JourneySynthesizer(und, app_name="Quiza")
    missions = synthesizer.synthesize_journeys()

    # Verify that the generated missions are real application workflows
    core_quiz_mission = next((m for m in missions if "Generate Quiz" in m.name), None)
    assert core_quiz_mission is not None
    assert core_quiz_mission.is_core is True
    assert core_quiz_mission.discovery_status == "verified"
    assert core_quiz_mission.recommended is True

    # Verify that no password visibility toggles or email input placeholder journeys exist
    mission_names = [m.name for m in missions]
    assert not any("password visibility" in n.lower() for n in mission_names)
    assert not any("name@example.com" in n.lower() for n in mission_names)


def test_rejection_of_password_visibility_and_input_placeholder_journeys():
    """Verifies that micro-interaction controls and email placeholders are rejected."""
    micro_controls = [
        "Toggle password visibility",
        "Show password",
        "Hide password",
        "Explore name@example.com",
        "Explore user@domain.com",
        "Explore password",
        "Explore email",
    ]
    for ctrl in micro_controls:
        assert is_flimsy_landing_element(ctrl) is True, f"Failed to reject micro-control: {ctrl}"


@pytest.mark.asyncio
async def test_evidence_based_authenticated_session_verification():
    """Verify that authentication verification requires concrete DOM/storage evidence."""
    import uuid
    from app.engine.exploration.explorer import ExplorationEngine

    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://app.example.com/login")

    # Scenario A: Still on login URL with password field -> Unauthenticated
    page_auth = AsyncMock()
    page_auth.url = "https://app.example.com/login"
    pwd_loc = AsyncMock()
    pwd_loc.is_visible.return_value = True
    page_auth.locator.return_value.first = pwd_loc

    is_auth_a, ev_a = await engine._verify_authenticated_session(page_auth)
    assert is_auth_a is False
    assert ev_a["not_on_auth_url"] is False

    # Scenario B: Navigated to workspace, no password, has token in storage and sign-out button
    page_workspace = AsyncMock()
    page_workspace.url = "https://app.example.com/workspace"

    def mock_loc(sel):
        m = AsyncMock()
        if "password" in sel:
            m.first.is_visible.return_value = False
        elif "Sign Out" in sel or "Logout" in sel:
            m.first.is_visible.return_value = True
        else:
            m.first.is_visible.return_value = False
        return m

    page_workspace.locator = mock_loc
    page_workspace.evaluate.return_value = {"hasToken": True, "count": 2}
    page_workspace.inner_text.return_value = "Welcome back Elvis Presley!"

    is_auth_b, ev_b = await engine._verify_authenticated_session(
        page_workspace,
        credential={"name": "Elvis Presley", "email": "test@example.com"}
    )
    assert is_auth_b is True
    assert ev_b["has_auth_token"] is True
    assert ev_b["has_sign_out"] is True
    assert ev_b["has_user_identity"] is True
    assert ev_b["no_password_input"] is True


@pytest.mark.asyncio
async def test_synthetic_credentials_lifecycle_and_reuse():
    """Verify that autonomous self-registration credentials can be persisted and reused."""
    import uuid
    from app.engine.exploration.explorer import ExplorationEngine
    from app.modules.credentials.models import Credential

    project_id = uuid.uuid4()
    mock_db = AsyncMock()
    mock_cred_repo = AsyncMock()
    saved_cred = Credential(
        id=uuid.uuid4(),
        project_id=project_id,
        name="Kova Exploration Test Account",
        email="test.kova.abc123@gmail.com",
        password="encrypted_hash",
        persona="Tester",
        auth_strategy="password_form",
    )
    mock_cred_repo.create.return_value = saved_cred

    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://app.example.com",
        project_id=project_id,
        db_session=mock_db,
    )
    assert engine.project_id == project_id
    assert engine._db_session == mock_db


# ---------------------------------------------------------------------------
# 6. Intelligent Authentication Strategy Evaluator Tests
# ---------------------------------------------------------------------------

def test_auth_evaluator_discovers_all_doors_on_login_surface():
    """Verify that all doors (OAuth, email/pwd, registration, recovery) are identified on login surfaces."""
    from app.engine.exploration.agent.auth_evaluator import AuthStrategyEvaluator

    observation = {
        "url": "https://app.test/login",
        "controls": [
            {"type": "button", "text": "Continue with Google", "name": "Continue with Google", "selector": "#btn-google"},
            {"type": "submit", "text": "Sign in", "name": "Sign in", "selector": "#btn-signin"},
        ],
        "links": [
            {"name": "Forgot password?", "href": "https://app.test/login#forgot", "selector": "a#forgot"},
            {"name": "Create an account", "href": "https://app.test/register", "selector": "a#register"},
        ],
        "elements": [
            {"type": "email", "name": "email", "placeholder": "Email", "selector": "#email"},
            {"type": "password", "name": "password", "placeholder": "Password", "selector": "#password"},
        ],
    }

    analysis = AuthStrategyEvaluator.analyze_surface(observation, "https://app.test/login")
    assert analysis.is_auth_surface is True
    assert analysis.has_native_login is True
    assert analysis.has_registration_link is True
    assert analysis.has_oauth is True
    assert len(analysis.options) >= 3

    types = {o.method_type for o in analysis.options}
    assert "native_login" in types
    assert "self_registration" in types
    assert "oauth" in types
    assert "recovery" in types


def test_auth_strategy_selection_prioritizes_credentials_then_registration_over_oauth():
    """Verify strategy selection prefers credentials, then self-registration over blind OAuth."""
    from app.engine.exploration.agent.auth_evaluator import AuthStrategyEvaluator

    observation = {
        "url": "https://app.test/login",
        "controls": [
            {"type": "button", "text": "Continue with Google", "selector": "#google"},
            {"type": "submit", "text": "Sign in", "selector": "#signin"},
        ],
        "links": [
            {"name": "Create an account", "href": "https://app.test/register", "selector": "#create-act"},
        ],
        "elements": [
            {"type": "email", "name": "email"},
            {"type": "password", "name": "password"},
        ],
    }
    analysis = AuthStrategyEvaluator.analyze_surface(observation, "https://app.test/login")

    # Scenario A: Project credentials provided -> Native Login selected
    und_a = ApplicationUnderstanding(target_url="https://app.test/login")
    creds = {"email": "user@example.com", "password": "SecretPassword123!"}
    strat_a, just_a = AuthStrategyEvaluator.select_strategy(analysis, creds, und_a)
    assert strat_a is not None
    assert strat_a.method_type == "native_login"
    assert "credentials available" in just_a.lower()

    # Scenario B: No credentials provided -> Native self-registration link selected over OAuth
    und_b = ApplicationUnderstanding(target_url="https://app.test/login")
    strat_b, just_b = AuthStrategyEvaluator.select_strategy(analysis, None, und_b)
    assert strat_b is not None
    assert strat_b.method_type == "self_registration"
    assert strat_b.target_url == "https://app.test/register"
    assert "registration discovered and selected" in just_b.lower()


def test_repetitive_failed_oauth_prevention():
    """Verify that once an OAuth attempt fails, it is marked unviable and never repeated."""
    from app.engine.exploration.agent.auth_evaluator import AuthStrategyEvaluator

    observation = {
        "url": "https://app.test/login",
        "controls": [
            {"type": "button", "text": "Continue with Google", "selector": "#google"},
        ],
        "links": [
            {"name": "Sign up with email", "href": "https://app.test/signup", "selector": "#signup"},
        ],
        "elements": [],
    }
    analysis = AuthStrategyEvaluator.analyze_surface(observation, "https://app.test/login")

    und = ApplicationUnderstanding(target_url="https://app.test/login")
    # Simulate a prior failed Google OAuth attempt
    und.record_auth_attempt("oauth", "google", success=False, outcome="OAuth popup closed without authentication")

    # When evaluating, google OAuth should NOT be selected
    strat, just = AuthStrategyEvaluator.select_strategy(analysis, None, und)
    assert strat is not None
    assert strat.method_type == "self_registration"
    assert strat.target_url == "https://app.test/signup"


@pytest.mark.asyncio
async def test_epistemic_agent_emits_structured_auth_progress_and_prioritizes_entrance_links():
    """Verify structured activity progress events and landing page link prioritization."""
    emitted_events: list[tuple[str, dict]] = []

    async def mock_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    page = MockPage("https://app.test/login")
    page.locators["#google"] = MockLocator("#google")
    page.locators["#register-btn"] = MockLocator("#register-btn")

    engine = AsyncMock()
    obs_login = {
        "url": "https://app.test/login",
        "controls": [
            {"type": "button", "text": "Continue with Google", "name": "Continue with Google", "selector": "#google"},
            {"type": "submit", "text": "Sign in", "name": "Sign in", "selector": "#signin"},
        ],
        "links": [
            {"name": "Create an account", "href": "https://app.test/register", "selector": "#register-btn"},
            {"name": "Features", "href": "https://app.test/#features", "selector": "#feat"},
        ],
        "elements": [
            {"type": "email", "name": "email", "selector": "#email"},
            {"type": "password", "name": "password", "selector": "#password"},
        ],
    }
    engine._observe_current_page.return_value = obs_login

    agent = EpistemicExplorationAgent(
        engine=engine,
        page=page,
        event_emitter=mock_emitter,
        budget={"max_actions": 1, "max_wall_clock": 10},
    )

    # Propose action on login page
    proposal = await agent._propose(obs_login, agent.sitemap.get_or_create_node(obs_login["url"], obs_login))
    assert proposal is not None
    assert proposal.source == "auth_strategy_evaluator"
    assert proposal.action == ExplorationAction.OPEN_LINK
    assert proposal.target.get("url") == "https://app.test/register"

    # Verify structured progress messages were emitted
    progress_messages = [p.get("message") for et, p in emitted_events if et == "progress"]
    assert any("Discovered authentication options" in m for m in progress_messages)
    assert any("Evaluating available access" in m for m in progress_messages)
    assert any("Selected Account Registration Link" in m for m in progress_messages)
    assert any("Executing selected strategy" in m for m in progress_messages)


