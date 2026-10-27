import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.engine.browser.readiness import PageReadiness, classify_page, PageSignals


def make_huntly_interstitial():
    return PageSignals(
        requested_url="https://huntly-0pgj.onrender.com/",
        observed_url="https://huntly-0pgj.onrender.com/",
        title="Render",
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


def test_scenario_a_application_becomes_ready_after_delay():
    first = classify_page(make_huntly_interstitial())
    assert first.state == PageReadiness.HOSTING_INTERSTITIAL
    # After delay becomes ready
    second = classify_page(make_huntly_ready())
    assert second.state == PageReadiness.APPLICATION_READY
    # Interstitial must not be accepted as app
    assert first.state != PageReadiness.APPLICATION_READY


def test_scenario_b_application_never_becomes_ready():
    first = classify_page(make_huntly_interstitial())
    assert first.state == PageReadiness.HOSTING_INTERSTITIAL
    # Remains unresolved
    # No app mission should be generated from interstitial
    # Just verify classification remains non-ready
    assert first.is_ready is False
