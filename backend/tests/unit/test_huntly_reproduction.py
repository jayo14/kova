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


@pytest.mark.asyncio
async def test_huntly_scenario_b_engine_run_end_to_end(monkeypatch):
    """End-to-end explorer.run() for Scenario B: unresolved hosting startup produces BLOCKED with 0 missions."""
    mock_browser = AsyncMock()
    mock_browser.is_started = True
    mock_page = AsyncMock()
    mock_page.url = "https://huntly-0pgj.onrender.com/"
    mock_page.title = AsyncMock(return_value="Render - Application loading")
    mock_page.inner_text = AsyncMock(return_value="Incoming HTTP request detected. Service waking up. Allocating compute resources. START BUILDING ON RENDER TODAY")
    mock_page.evaluate = AsyncMock(return_value={
        "interactive": 1,
        "forms": 0,
        "links": 1,
        "navs": 0,
        "headings": 1,
        "hasPassword": False,
        "hasEmail": False,
    })
    mock_page.goto = AsyncMock(return_value=MagicMock(status=200))
    mock_page.wait_for_load_state = AsyncMock()
    mock_browser.page = mock_page

    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://huntly-0pgj.onrender.com/",
    )
    explorer._browser = mock_browser

    from app.config.settings import settings
    monkeypatch.setattr(settings, "PAGE_READINESS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "PAGE_READINESS_RETRY_INTERVALS", "0.01,0.01")

    result = await explorer.explore()
    assert result["status"] == ExplorationStatus.BLOCKED
    assert len(result["candidate_missions"]) == 0
    assert len(result["discoveries"]) == 0
    assert "hosting" in result["error_message"].lower() or "ready" in result["error_message"].lower()
    assert result["readiness"]["state"] == PageReadiness.HOSTING_INTERSTITIAL


@pytest.mark.asyncio
async def test_huntly_scenario_a_engine_run_end_to_end(monkeypatch):
    """End-to-end explorer.explore() for Scenario A: startup recovers to Huntly, producing valid Huntly missions."""
    mock_browser = AsyncMock()
    mock_browser.is_started = True
    mock_page = AsyncMock()
    mock_page.url = "https://huntly-0pgj.onrender.com/"

    probe_call = 0

    async def fake_title():
        nonlocal probe_call
        probe_call += 1
        return "Render - Application loading" if probe_call <= 1 else "Huntly - Bookmark & Insights"

    async def fake_inner_text(sel="body"):
        return (
            "Incoming HTTP request detected. Service waking up. Allocating compute resources. START BUILDING ON RENDER TODAY"
            if probe_call <= 1
            else "Huntly. Discover, save and organize content. Search your bookmarks. Add new bookmark. Dashboard. Explore collections."
        )

    async def fake_evaluate(script):
        if probe_call <= 1:
            return {"interactive": 1, "forms": 0, "links": 1, "navs": 0, "headings": 1, "hasPassword": False, "hasEmail": False}
        return {"interactive": 10, "forms": 1, "links": 12, "navs": 4, "headings": 3, "hasPassword": False, "hasEmail": False}

    async def fake_goto(url, **kwargs):
        return MagicMock(status=200)

    mock_page.title = fake_title
    mock_page.inner_text = fake_inner_text
    mock_page.evaluate = fake_evaluate
    mock_page.goto = fake_goto
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=b"fake-png")
    mock_browser.page = mock_page
    mock_browser.observe = AsyncMock(return_value={
        "title": "Huntly",
        "elements": [
            {"type": "button", "name": "Save Bookmark"},
            {"type": "button", "name": "Search Collections"},
        ],
        "text": "Huntly helps teams curate knowledge and bookmarks.",
    })

    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://huntly-0pgj.onrender.com/",
    )
    explorer._browser = mock_browser

    from app.config.settings import settings
    monkeypatch.setattr(settings, "PAGE_READINESS_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(settings, "PAGE_READINESS_RETRY_INTERVALS", "0.01,0.01")
    monkeypatch.setattr(explorer, "_analyze_routes", lambda p, u, **kw: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(explorer, "_stream_page_exploration", lambda p: asyncio.sleep(0))
    monkeypatch.setattr(explorer, "_capture_and_emit_screenshot", lambda p, **kw: asyncio.sleep(0))

    result = await explorer.explore()
    assert result["status"] == ExplorationStatus.READY
    assert len(result["candidate_missions"]) >= 1
    for m in result["candidate_missions"]:
        assert "render" not in m["name"].lower()
        assert "start building" not in m["name"].lower()
    assert any("Bookmark" in m["name"] or "Search" in m["name"] for m in result["candidate_missions"])
