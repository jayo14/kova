import uuid
import pytest
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.schemas import DiscoveredMission
from app.modules.product_graph.schemas import DiscoveryResult


class DummyPage:
    def __init__(self, url="https://example.com"):
        self.url = url


def test_generate_fast_path_missions_without_goal():
    engine = ExplorationEngine(url="https://example.com", exploration_id=uuid.uuid4())
    page = DummyPage("https://example.com")
    observation = {
        "title": "Example App",
        "elements": [
            {"type": "button", "name": "Get Started", "selector": "#cta"},
            {"type": "a", "name": "Features", "selector": "a.features"},
            {"type": "button", "name": "Sign Out", "selector": "#signout"}, # Should be skipped
            {"type": "a", "name": "Pricing", "selector": "a.pricing"},
        ],
    }

    missions = engine._generate_fast_path_missions(page, observation, goal=None)
    assert len(missions) >= 2
    assert all(isinstance(m, DiscoveredMission) for m in missions)
    assert any("Get Started" in m.name for m in missions)
    assert not any("Sign Out" in m.name for m in missions)
    assert any(m.recommended for m in missions)
    # Check steps don't have excessive waits
    for m in missions:
        for step in m.steps:
            if step.get("type") == "wait":
                assert int(step.get("value", "0")) <= 500


def test_generate_fast_path_missions_with_goal():
    engine = ExplorationEngine(url="https://example.com", exploration_id=uuid.uuid4(), goal="Purchase a subscription")
    page = DummyPage("https://example.com")
    observation = {
        "title": "Example App",
        "elements": [
            {"type": "button", "name": "Pricing", "selector": "#pricing"},
            {"type": "button", "name": "Documentation", "selector": "#docs"},
        ],
    }

    missions = engine._generate_fast_path_missions(page, observation, goal="Purchase a subscription")
    assert len(missions) >= 1
    assert any("Purchase a subscription" in m.name for m in missions)
    assert missions[0].recommended is True


def test_synthesize_fast_discovery_result():
    project_id = uuid.uuid4()
    engine = ExplorationEngine(
        url="https://example.com/dashboard",
        exploration_id=project_id,
        project_id=project_id,
        goal="Test feature workflow",
    )

    route_map = [
        {"path": "/analytics", "title": "Analytics", "accessible": True},
        {"path": "/settings", "title": "Settings", "requires_auth": True},
    ]
    interactive_elements = [
        {"name": "Create Project", "selector": "#create-btn", "type": "button"},
        {"name": "Export Data", "selector": "#export-btn", "type": "button"},
    ]

    result = engine._synthesize_fast_discovery_result(
        page_url="https://example.com/dashboard",
        page_title="Dashboard",
        route_map=route_map,
        interactive_elements=interactive_elements,
        persona_name="Admin",
    )

    assert isinstance(result, DiscoveryResult)
    assert len(result.personas) == 1
    assert result.personas[0].name == "Admin"
    assert len(result.pages) >= 3  # dashboard + analytics + settings
    assert any(p.url_pattern == "/dashboard" for p in result.pages)
    assert any(p.url_pattern == "/analytics" for p in result.pages)
    assert len(result.actions) == 2
    assert any("Create Project" in a.name for a in result.actions)
    assert len(result.goals) == 1
    assert result.goals[0].name == "Test feature workflow"

    # Must be valid for model_dump and re-validation
    dumped = result.model_dump(mode="json")
    re_validated = DiscoveryResult.model_validate(dumped)
    assert len(re_validated.pages) == len(result.pages)
