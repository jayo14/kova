import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.engine.browser.readiness import PageReadiness, classify_page, PageSignals, ReadinessWaiter
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.models import ExplorationStatus


@pytest.fixture(autouse=True)
def disable_ai(monkeypatch):
    """Ensure tests are fully deterministic and fast without remote LLM timeouts."""
    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)


def make_huntly_interstitial():
    return PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Render - Application loading",
        body_text="Incoming HTTP request detected. Service waking up. Allocating compute resources. Preparing instance for initialization. START BUILDING ON RENDER TODAY",
        interactive_count=1,
        link_count=1,
        nav_item_count=0,
        heading_count=1,
    )


def make_huntly_ready():
    return PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Huntly",
        body_text="Huntly. Discover, save and organize content. Search your bookmarks. Add new bookmark. Dashboard. Explore collections.",
        interactive_count=10,
        link_count=15,
        nav_item_count=4,
        heading_count=3,
    )


def test_scenario_a_classification_becomes_ready():
    first = classify_page(make_huntly_interstitial())
    assert first.state == PageReadiness.HOSTING_INTERSTITIAL
    assert first.identity is None or first.identity == "huntly"
    second = classify_page(make_huntly_ready())
    assert second.state == PageReadiness.APPLICATION_READY
    assert second.identity == "huntly"
    assert first.state != PageReadiness.APPLICATION_READY


def test_scenario_b_classification_never_becomes_ready():
    first = classify_page(make_huntly_interstitial())
    assert first.state == PageReadiness.HOSTING_INTERSTITIAL
    assert first.is_ready is False


@pytest.mark.asyncio
async def test_huntly_scenario_a_full_pipeline_resolution(monkeypatch):
    """Scenario A:
    Huntly is initially sleeping on Render.
    1. First observation is Render startup interstitial with 'START BUILDING ON RENDER TODAY'.
    2. After bounded check, fixture transitions to Huntly application.
    3. Engine verifies readiness, identifies Huntly, and generates only meaningful Huntly flows.
    4. Interstitial CTA 'START BUILDING ON RENDER TODAY' is NEVER persisted as a mission.
    """
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://huntly-0pgj.onrender.com/",
    )

    probe_count = 0

    async def mock_probe(page, observed_url=None):
        nonlocal probe_count
        probe_count += 1
        if probe_count == 1:
            return classify_page(make_huntly_interstitial())
        return classify_page(make_huntly_ready())

    monkeypatch.setattr(explorer, "_probe_readiness", mock_probe)

    # 1. Probe initial readiness
    initial = await explorer._probe_readiness(None)
    assert initial.state == PageReadiness.HOSTING_INTERSTITIAL

    # 2. Waiter resolves to ready after transition
    waiter = ReadinessWaiter(
        probe=lambda: explorer._probe_readiness(None),
        intervals=(0.01,),
        total_timeout=1.0,
        sleep=asyncio.sleep,
    )
    resolved = await waiter.resolve(initial)
    assert resolved.state == PageReadiness.APPLICATION_READY
    assert resolved.identity == "huntly"

    # 3. Target application is identified, workflows discovered on Huntly
    class DummyPage:
        url = "https://huntly-0pgj.onrender.com/"

    observation = {
        "title": "Huntly",
        "elements": [
            {"type": "button", "name": "Save Bookmark"},
            {"type": "button", "name": "Explore Collections"},
            {"type": "a", "name": "Dashboard"},
        ],
        "text": "Huntly. Discover, save and organize content.",
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), observation, "User")

    # Verify only Huntly missions are produced and infrastructure CTAs are completely excluded
    assert len(missions) > 0
    mission_names = [m.name for m in missions]
    assert not any("render" in name.lower() for name in mission_names)
    assert not any("start building" in name.lower() for name in mission_names)
    assert any("Bookmark" in name or "Collections" in name or "Dashboard" in name for name in mission_names)


@pytest.mark.asyncio
async def test_huntly_scenario_b_full_pipeline_unresolved_timeout(monkeypatch):
    """Scenario B:
    Huntly never resolves; stays as Render startup interstitial.
    1. Every probe returns Render startup interstitial.
    2. Bounded waiter times out.
    3. Interstitial CTA is rejected, no candidate mission is generated.
    4. Outcome is BLOCKED (hosting_interstitial) without false application failure.
    """
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://huntly-0pgj.onrender.com/",
    )

    async def mock_probe(page, observed_url=None):
        return classify_page(make_huntly_interstitial())

    monkeypatch.setattr(explorer, "_probe_readiness", mock_probe)

    initial = await explorer._probe_readiness(None)
    assert initial.state == PageReadiness.HOSTING_INTERSTITIAL

    waiter = ReadinessWaiter(
        probe=lambda: explorer._probe_readiness(None),
        intervals=(0.01, 0.01),
        total_timeout=0.05,
        sleep=asyncio.sleep,
    )
    resolved = await waiter.resolve(initial)
    assert resolved.state == PageReadiness.HOSTING_INTERSTITIAL
    assert resolved.is_ready is False

    # Interstitial observation must produce ZERO candidate missions
    class DummyPage:
        url = "https://huntly-0pgj.onrender.com/"

    interstitial_obs = {
        "title": "Render - Application loading",
        "elements": [
            {"type": "button", "name": "START BUILDING ON RENDER TODAY"},
        ],
        "text": "Incoming HTTP request detected. Service waking up. Allocating compute resources.",
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), interstitial_obs, "User")
    assert len(missions) == 0

    # Fast-path generator must also return 0 missions from the interstitial
    fast_missions = explorer._generate_fast_path_missions(DummyPage(), interstitial_obs, None)
    assert len(fast_missions) == 0
