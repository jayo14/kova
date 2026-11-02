import json
from pathlib import Path
import pytest

from app.engine.browser.platform_wake import detect_platform_wake


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "platform_interstitials"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def test_render_waking_detected():
    data = load_fixture("render_waking.json")
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
    assert result.message == "The host (Render) is waking up"


def test_heroku_error_detected():
    data = load_fixture("heroku_error.json")
    result = detect_platform_wake(
        headers=data["headers"],
        status_code=data["status_code"],
        title=data["title"],
        body_text=data["body"],
        url="https://myapp.herokuapp.com/",
    )
    assert result.matched is True
    assert result.platform == "Heroku"
    assert result.is_waking is False


def test_railway_error_detected():
    data = load_fixture("railway_error.json")
    result = detect_platform_wake(
        headers=data["headers"],
        status_code=data["status_code"],
        title=data["title"],
        body_text=data["body"],
        url="https://myapp.railway.app/",
    )
    assert result.matched is True
    assert result.platform == "Railway"


def test_fly_error_detected():
    data = load_fixture("fly_error.json")
    result = detect_platform_wake(
        headers=data["headers"],
        status_code=data["status_code"],
        title=data["title"],
        body_text=data["body"],
        url="https://myapp.fly.dev/",
    )
    assert result.matched is True
    assert result.platform == "Fly.io"


def test_vercel_error_detected():
    data = load_fixture("vercel_error.json")
    result = detect_platform_wake(
        headers=data["headers"],
        status_code=data["status_code"],
        title=data["title"],
        body_text=data["body"],
        url="https://myapp.vercel.app/",
    )
    assert result.matched is True
    assert result.platform == "Vercel"


def test_netlify_error_detected():
    data = load_fixture("netlify_error.json")
    result = detect_platform_wake(
        headers=data["headers"],
        status_code=data["status_code"],
        title=data["title"],
        body_text=data["body"],
        url="https://myapp.netlify.app/",
    )
    assert result.matched is True
    assert result.platform == "Netlify"


def test_normal_app_page_does_not_match():
    result = detect_platform_wake(
        headers={"content-type": "text/html; charset=utf-8"},
        status_code=200,
        title="Quiza AI - Quiz Generator",
        body_text="Generate quizzes and flashcards with AI. Sign up for free.",
        url="https://quiza-ai.vercel.app/",
    )
    assert result.matched is False
    assert result.message is None
