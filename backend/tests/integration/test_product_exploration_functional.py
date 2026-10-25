"""Integration test for functional product discovery and journey ranking on real applications (e.g. Log2Def)."""

import uuid
import pytest
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.journey_validator import is_vague_outcome


@pytest.fixture(autouse=True)
def mock_ai_provider(monkeypatch):
    """Ensure deterministic exploration behavior in test."""
    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)


class MockPage:
    def __init__(self, url: str):
        self.url = url

    async def evaluate(self, script: str):
        return []


@pytest.mark.asyncio
async def test_log2def_style_app_exploration_generates_functional_workflows():
    """Verify that exploring a Log2Def-style application (report creation, mock defence)
    produces functional, outcome-driven candidate journeys and recommends the core workflow
    rather than landing navigation or login.
    """
    base_url = "https://log2def.vercel.app"
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url=base_url,
    )

    observation = {
        "title": "Log2Def - SIWES Technical Report & Mock Defence Preparation",
        "text": (
            "Transform your SIWES logbook entries into complete, industry-standard "
            "technical reports and prepare for your defence with automated mock sessions."
        ),
        "elements": [
            {"type": "link", "name": "Features", "selector": "#features-link"},
            {"type": "link", "name": "Get started", "selector": "#get-started-btn"},
            {"type": "button", "name": "Create your report", "selector": "#create-report-btn"},
            {"type": "button", "name": "Mock defence", "selector": "#mock-defence-btn"},
            {"type": "link", "name": "How it works", "selector": "#how-it-works-link"},
            {"type": "link", "name": "Sign in", "selector": "#signin-link"},
        ],
    }

    dummy_page = MockPage(base_url)
    discoveries, missions = await engine._discover_workflows(dummy_page, observation, "Student")

    assert len(missions) >= 2, "Exploration should discover multiple journey candidates"

    # 1. Mission Quality & Outcome-Driven Checks:
    # No mission should have a vague outcome
    for m in missions:
        assert not is_vague_outcome(m.expected_outcome), (
            f"Mission '{m.name}' has vague outcome: '{m.expected_outcome}'"
        )
        assert m.user_goal, f"Mission '{m.name}' is missing user_goal"
        assert m.expected_outcome, f"Mission '{m.name}' is missing expected_outcome"

    # 2. Functional workflows present:
    mission_names = [m.name for m in missions]
    has_report_workflow = any("report" in n.lower() for n in mission_names)
    has_defence_workflow = any("defence" in n.lower() or "defense" in n.lower() for n in mission_names)

    assert has_report_workflow, f"Expected report generation workflow in {mission_names}"
    assert has_defence_workflow, f"Expected mock defence workflow in {mission_names}"

    # 3. Check that the report workflow has multi-step actions (inputting content & generating)
    report_mission = next(m for m in missions if "report" in m.name.lower())
    assert report_mission.classification == "functional"
    assert report_mission.is_core is True
    assert any(s.get("type") in ("type", "fill") for s in report_mission.steps), (
        "Report workflow must include data entry steps, not just clicking"
    )
    assert report_mission.successCondition is not None

    # 4. Explainable Ranking Recommendation:
    # The recommended mission must be a core functional workflow (NOT auth, NOT shallow nav)
    recommended_missions = [m for m in missions if m.recommended]
    assert len(recommended_missions) == 1, "Exactly one mission should be recommended"
    rec = recommended_missions[0]

    assert rec.category not in ("auth", "navigation"), (
        f"Recommended mission should not be auth or navigation, got category '{rec.category}' ({rec.name})"
    )
    assert rec.is_core is True, f"Recommended mission must be a core product capability: {rec.name}"
    assert rec.ranking_rationale is not None, "Recommended mission must provide ranking_rationale"
    assert "core capability" in rec.ranking_rationale.lower()

    # 5. Recommendation message from engine:
    rec_text = engine._generate_recommendation(missions)
    assert rec.ranking_rationale in rec_text or rec.name in rec_text


@pytest.mark.asyncio
async def test_goal_directed_exploration_prioritizes_specific_target():
    """When a user specifies a goal (e.g. 'practice mock defence'), the engine aligns
    the recommended journey specifically to that goal.
    """
    base_url = "https://log2def.vercel.app"
    engine = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url=base_url,
        goal="practice mock defence",
    )

    observation = {
        "title": "Log2Def",
        "text": "Logbook reports and defence simulation",
        "elements": [
            {"type": "button", "name": "Create your report", "selector": "#create-report-btn"},
            {"type": "button", "name": "Mock defence", "selector": "#mock-defence-btn"},
            {"type": "link", "name": "Sign in", "selector": "#signin-link"},
        ],
    }

    dummy_page = MockPage(base_url)
    discoveries, missions = await engine._discover_workflows(dummy_page, observation, "Student")

    assert len(missions) >= 1
    rec = next(m for m in missions if m.recommended)
    assert "defence" in rec.name.lower() or "defense" in rec.name.lower()
