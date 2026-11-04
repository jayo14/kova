"""Autonomous Application Exploration and Epistemic Understanding Test Suite.

Verifies application-agnostic intelligence, hypothesis testing, authentication
discovery, state transition tracking, and grounded journey synthesis across
diverse, unfamiliar web applications.
"""

import pytest
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

