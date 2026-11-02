import json
from pathlib import Path
import pytest

from app.engine.browser.platform_wake import detect_platform_wake


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "platform_interstitials"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def test_synthetic_render_waking_detected():
    """Synthetic Render fixture matches wake state for testing polling logic only."""
    data = load_fixture("synthetic_render_waking.json")
    assert data.get("type") == "synthetic"
    result = detect_platform_wake(
        headers=data["headers"],
        status_code=data["status_code"],
        title=data["title"],
        body_text=data["body"],
        url="https://myapp.onrender.com/",
    )
    assert result.matched is True
    assert result.platform == "Render"
    assert result.is_waking is True
    assert result.is_synthetic is True
    assert result.message == "The hosting service (Render) is waking up"


def test_headers_alone_never_match_wake():
    """Amendment 1: Platform headers only identify the platform. Never match on headers alone."""
    result = detect_platform_wake(
        headers={
            "server": "Render",
            "x-render-origin-server": "render-gateway",
            "via": "1.1 vegur",
        },
        status_code=200,
        title="My Awesome Store",
        body_text="Welcome to my eCommerce store. Buy products today!",
        url="https://mystore.onrender.com/",
    )
    assert result.matched is False
    assert result.message is None


def test_unverified_signatures_do_not_emit_wake():
    """Amendment 2: Unverified signatures do not emit wake messages until real captures supplied."""
    result = detect_platform_wake(
        headers={
            "server": "fly",
            "fly-request-id": "fly-12345",
        },
        status_code=503,
        title="503 Service Unavailable",
        body_text="machine starting up",
        url="https://myapp.fly.dev/",
    )
    assert result.matched is False
    assert result.message is None


def test_normal_app_page_does_not_match():
    """Ordinary pages with no platform headers or wake markers do not match."""
    result = detect_platform_wake(
        headers={"content-type": "text/html; charset=utf-8"},
        status_code=200,
        title="Quiza AI - Quiz Generator",
        body_text="Generate quizzes and flashcards with AI. Sign up for free.",
        url="https://quiza-ai.vercel.app/",
    )
    assert result.matched is False
    assert result.message is None
