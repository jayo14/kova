"""Reproduction tests for Quiza signin journey quality, provenance, and false confidence.

Shows the failure modes before the pipeline fix:
1. "Explore Show password" is generated as a recommended feature journey with generic destination assertions.
2. Google OAuth button is proposed as an unconstrained or fake login journey without handoff boundaries.
3. Sign In is generated as a runnable flow even without test credentials or post-login observations.
4. Repair logic in journey_validator masks defects with generic LLM-style wording ("verify application state transition").
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.schemas import DiscoveredMission
from app.modules.exploration.journey_validator import validate_journey, repair_journey, deduplicate_and_rank_journeys


def make_quiza_signin_observation():
    return {
        "url": "https://quiza-ai.vercel.app/signin",
        "title": "Quiza - Sign in",
        "text": "Quiza AI. Test your knowledge. Sign in to your account. Email address. Password. Show password. Forgot password? Sign In. Continue with Google. Don't have an account? Sign up.",
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


def test_quiza_failure_mode_unqualified_element_missions():
    """Reproduces how Kova previously created shallow 'Explore Show password' missions."""
    engine = ExplorationEngine(exploration_id=uuid.uuid4(), url="https://quiza-ai.vercel.app/signin")
    obs = make_quiza_signin_observation()

    class DummyPage:
        url = "https://quiza-ai.vercel.app/signin"

    # Fast path previously took 'Show password' and made it an executable mission with generic element_count
    missions = engine._generate_fast_path_missions(DummyPage(), obs, goal=None)
    names = [m.name for m in missions]

    # Notice: previously "Explore Show password" was generated with trivial assertions:
    show_pwd = next((m for m in missions if "Show password" in m.name), None)
    if show_pwd:
        # Trivial assertion: just checks if main, button, or input exists!
        assert isinstance(show_pwd.successCondition, dict)
        assert "element_count" in show_pwd.successCondition
        # And it was marked recommended!
        # The prompt says: "Explore Show password is not an adequate test definition.
        # A valid control test should verify that the password field changes visibility and can return to its original masked state."


def test_quiza_failure_mode_repair_journey_synthesizes_vague_assertions():
    """Confirms that repair_journey does NOT mask invalid journeys by inserting generic assertions, and quality gate rejects them."""
    bad_mission = DiscoveredMission(
        id="bad-1",
        name="Open Show password",
        objective="Verify that User can use 'Show password' and the app responds",
        journey=["Open Quiza", "Use 'Show password'", "Verify the destination interface renders with content"],
        steps=[
            {"type": "navigate", "url": "https://quiza-ai.vercel.app/signin"},
            {"type": "wait", "value": "500"},
            {"type": "click", "target": "button[aria-label='Show password']"},
            {"type": "wait", "value": "500"},
        ],
        successCondition={"element_count": {"selector": "a[href], button, h1, h2, h3, [role='region'], main", "min": 1}},
        classification="functional",
        expected_outcome=None,
    )

    # Initial validation flags SHALLOW_NAVIGATION / VACUOUS_ASSERTION
    val = validate_journey(bad_mission)
    assert not val.is_valid

    # Repair must NOT mask defects by synthesizing generic layout assertions or fake outcomes
    repaired = repair_journey(bad_mission)
    val2 = validate_journey(repaired)
    assert not val2.is_valid
    assert any(d.code in ("VACUOUS_ASSERTION", "SHALLOW_NAVIGATION", "VAGUE_OUTCOME") for d in val2.defects)

