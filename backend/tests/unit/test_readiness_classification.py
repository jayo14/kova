import uuid

from app.engine.browser.readiness import (
    PageReadiness,
    PageSignals,
    ReadinessWaiter,
    classify_page,
)


def _base_signals(**kwargs) -> PageSignals:
    base = dict(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="",
        body_text="",
        http_status=None,
        redirect_chain=[],
        interactive_count=0,
        form_count=0,
        link_count=0,
        heading_count=0,
        nav_item_count=0,
        has_password_field=False,
        has_email_field=False,
    )
    base.update(kwargs)
    return PageSignals(**base)


def test_render_like_startup_interstitial_classified_as_hosting():
    signals = _base_signals(
        title="Render",
        body_text="Incoming HTTP request detected. Service waking up. Allocating compute resources. Preparing instance for initialization. START BUILDING ON RENDER TODAY",
        interactive_count=1,
        link_count=1,
        nav_item_count=0,
        heading_count=1,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.HOSTING_INTERSTITIAL
    assert "render" in res.reason.lower() or "hosting" in res.reason.lower() or "provider" in res.reason.lower()


def test_application_becomes_ready_after_delay():
    signals = _base_signals(
        title="Huntly - Home",
        body_text="Huntly helps teams discover insights. Browse projects. Search. Dashboard. Sign in.",
        interactive_count=6,
        link_count=10,
        nav_item_count=3,
        heading_count=2,
        form_count=0,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.APPLICATION_READY


def test_startup_never_resolves_loading():
    signals = _base_signals(
        title="Loading",
        body_text="Loading... Please wait. Initializing application.",
        interactive_count=0,
        link_count=0,
        nav_item_count=0,
        heading_count=0,
    )
    res = classify_page(signals)
    assert res.state in (PageReadiness.APPLICATION_LOADING, PageReadiness.HOSTING_INTERSTITIAL)


def test_hosting_error_page():
    signals = _base_signals(
        title="Application Error",
        body_text="Application error. Service unavailable.",
        interactive_count=0,
        http_status=503,
    )
    res = classify_page(signals)
    assert res.state in (PageReadiness.PROXY_OR_GATEWAY_ERROR, PageReadiness.APPLICATION_ERROR, PageReadiness.HOSTING_INTERSTITIAL)


def test_proxy_or_gateway_error():
    signals = _base_signals(
        http_status=502,
        body_text="Bad Gateway",
        interactive_count=0,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.PROXY_OR_GATEWAY_ERROR


def test_ordinary_application_landing_page_minimal_branding():
    signals = _base_signals(
        title="App",
        body_text="Welcome. Get started. Create new item.",
        interactive_count=4,
        link_count=6,
        nav_item_count=2,
        heading_count=2,
    )
    res = classify_page(signals)
    # Should be identifiable as application structure even with minimal branding
    assert res.state in (PageReadiness.APPLICATION_READY, PageReadiness.UNKNOWN_PAGE)


def test_legitimate_application_login_page():
    signals = _base_signals(
        title="Sign in",
        body_text="Sign in to your account. Email and password required.",
        interactive_count=3,
        form_count=1,
        has_password_field=True,
        has_email_field=True,
        heading_count=1,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.AUTHENTICATION_REQUIRED


def test_authentication_redirect():
    signals = _base_signals(
        requested_url="https://example.com/app",
        observed_url="https://example.com/login",
        title="Login",
        body_text="Sign in",
        form_count=1,
        has_password_field=True,
        interactive_count=3,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.AUTHENTICATION_REQUIRED


def test_unexpected_cross_origin_redirect():
    signals = _base_signals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://evil.example.com/",
        title="Phish",
        body_text="Login here",
        redirect_chain=["https://huntly-0pgj.onrender.com/"],
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.UNKNOWN_PAGE


def test_target_url_must_not_be_silently_replaced():
    signals = _base_signals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://other.example.com/page",
    )
    res = classify_page(signals)
    assert res.target_url == "https://huntly-0pgj.onrender.com/"


def test_application_with_zero_meaningful_controls():
    signals = _base_signals(
        title="Coming soon",
        body_text="Coming soon. We are launching soon.",
        interactive_count=0,
        link_count=0,
        nav_item_count=0,
        heading_count=1,
    )
    res = classify_page(signals)
    assert res.state != PageReadiness.APPLICATION_READY


def test_generic_cta_unrelated_to_target_not_making_ready():
    signals = _base_signals(
        title="Render",
        body_text="START BUILDING ON RENDER TODAY",
        interactive_count=1,
        link_count=0,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.HOSTING_INTERSTITIAL


def test_real_application_initially_slow_but_ready():
    signals = _base_signals(
        title="Dashboard",
        body_text="Dashboard. Projects. Reports. Analytics.",
        interactive_count=8,
        link_count=12,
        nav_item_count=4,
        heading_count=3,
    )
    res = classify_page(signals)
    assert res.state == PageReadiness.APPLICATION_READY


import asyncio
import pytest


@pytest.mark.asyncio
async def test_cancellation_during_readiness_wait():
    """14. Cancellation during the readiness wait."""
    probe_called = 0

    async def mock_probe():
        nonlocal probe_called
        probe_called += 1
        return classify_page(_base_signals(title="Render", body_text="Service waking up"))

    initial = classify_page(_base_signals(title="Render", body_text="Service waking up"))
    cancelled = True
    waiter = ReadinessWaiter(
        probe=mock_probe,
        intervals=(10.0, 10.0),
        total_timeout=60.0,
        sleep=asyncio.sleep,
    )
    result = await waiter.resolve(initial, is_cancelled=lambda: cancelled)
    # Must abort immediately when cancelled
    assert result.state == PageReadiness.HOSTING_INTERSTITIAL
    assert probe_called == 0


def test_provider_unavailable_deterministic_classification():
    """15. A provider-unavailable scenario where deterministic classification must still work."""
    signals = _base_signals(
        title="503 Service Unavailable",
        body_text="Service Unavailable",
        http_status=503,
    )
    res = classify_page(signals)
    assert res.state in (PageReadiness.PROXY_OR_GATEWAY_ERROR, PageReadiness.APPLICATION_ERROR, PageReadiness.HOSTING_INTERSTITIAL)


@pytest.mark.asyncio
async def test_interstitial_observation_never_becomes_persisted_mission(monkeypatch):
    """16. An interstitial observation that must never become a persisted application mission."""
    from app.engine.exploration.explorer import ExplorationEngine

    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://huntly-0pgj.onrender.com/",
    )

    class DummyPage:
        url = "https://huntly-0pgj.onrender.com/"

    interstitial_obs = {
        "title": "Render - Application loading",
        "elements": [
            {"type": "button", "name": "START BUILDING ON RENDER TODAY"},
            {"type": "button", "name": "Wake Up"},
            {"type": "button", "name": "View Logs"},
        ],
        "text": "Incoming HTTP request detected. Service waking up. Allocating compute resources.",
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), interstitial_obs, "User")
    assert len(missions) == 0

    fast = explorer._generate_fast_path_missions(DummyPage(), interstitial_obs, None)
    assert len(fast) == 0


@pytest.mark.asyncio
async def test_valid_application_produces_meaningful_verifiable_mission(monkeypatch):
    """17. A valid application observation that produces a meaningful, verifiable mission."""
    from app.engine.exploration.explorer import ExplorationEngine

    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://app.huntly.io",
    )

    class DummyPage:
        url = "https://app.huntly.io"

    app_obs = {
        "title": "Huntly Knowledge Workspace",
        "elements": [
            {"type": "button", "name": "Create Bookmark"},
            {"type": "button", "name": "Search Articles"},
        ],
        "text": "Huntly helps teams curate knowledge and bookmarks.",
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), app_obs, "User")
    assert len(missions) >= 1
    mission = missions[0]
    assert mission.recommended is True
    assert mission.category in ("feature", "navigation")
    assert mission.successCondition is not None
    assert len(mission.steps) > 0


@pytest.mark.asyncio
async def test_zero_valid_flows_and_unresolved_readiness_handling(monkeypatch):
    """18. Frontend handling of zero valid flows and unresolved readiness."""
    from app.engine.exploration.explorer import ExplorationEngine

    monkeypatch.setattr("app.engine.exploration.explorer.get_ai_provider", lambda: None)
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://empty-shell.example.com",
    )

    class DummyPage:
        url = "https://empty-shell.example.com"

    empty_obs = {
        "title": "Empty Shell",
        "elements": [],
        "text": "Nothing to interact with here.",
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), empty_obs, "Visitor")
    assert len(missions) == 0
    assert any("No Actionable" in d.label or "No Executable" in d.label for d in discoveries)

