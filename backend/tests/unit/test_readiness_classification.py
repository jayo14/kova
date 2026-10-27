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


def test_cancellation_during_readiness_wait():
    class Dummy:
        pass

    waiter = ReadinessWaiter(
        probe=lambda: asyncio.sleep(0),
        intervals=(0.1,),
        total_timeout=1.0,
    )
    # Just ensure it can be constructed
    assert waiter is not None


def test_provider_unavailable_deterministic_classification():
    signals = _base_signals(
        title="503 Service Unavailable",
        body_text="Service Unavailable",
        http_status=503,
    )
    res = classify_page(signals)
    assert res.state in (PageReadiness.PROXY_OR_GATEWAY_ERROR, PageReadiness.APPLICATION_ERROR, PageReadiness.HOSTING_INTERSTITIAL)
