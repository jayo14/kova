from __future__ import annotations

from typing import Any

import pytest

from app.config.settings import get_settings
from app.engine.exploration.agent.agent import ExplorationAgent
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.schemas import DiscoveryItem


class FakePage:
    def __init__(self, url: str):
        self.url = url
        self.goto_calls: list[str] = []

    async def goto(self, url: str, **_kwargs: Any) -> None:
        self.goto_calls.append(url)
        self.url = url


def _engine() -> ExplorationEngine:
    engine = object.__new__(ExplorationEngine)
    engine.url = "https://app.example.test/"
    engine.event_emitter = None
    return engine


def test_exploration_agent_enabled_by_default():
    assert get_settings().EXPLORATION_AGENT_ENABLED is True


def test_merge_agent_capabilities_is_a_noop_without_agent_result():
    existing = [DiscoveryItem(label="Dashboard")]

    assert ExplorationEngine._merge_agent_capabilities(existing, None) == existing


def test_merge_agent_capabilities_dedupes_and_appends():
    existing = [DiscoveryItem(label="Reports")]

    merged = ExplorationEngine._merge_agent_capabilities(
        existing,
        {
            "capabilities": [
                {"name": "reports", "kind": "button", "url": "https://app.example.test/"},
                {"name": "Sign in", "kind": "dialog", "url": "https://app.example.test/login"},
            ]
        },
    )

    assert [item.label for item in merged] == ["Reports", "Sign in"]
    assert merged[1].description == "Discovered dialog at https://app.example.test/login"


@pytest.mark.asyncio
async def test_agent_exploration_disabled_does_not_touch_page(monkeypatch):
    monkeypatch.setattr(get_settings(), "EXPLORATION_AGENT_ENABLED", False, raising=False)
    page = FakePage("https://app.example.test/")

    result = await _engine()._run_agent_exploration(page)

    assert result is None
    assert page.goto_calls == []


@pytest.mark.asyncio
async def test_agent_exploration_restores_page_and_emits(monkeypatch):
    monkeypatch.setattr(get_settings(), "EXPLORATION_AGENT_ENABLED", True, raising=False)
    events: list[tuple[str, dict]] = []

    async def emitter(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    async def fake_run(self, max_steps=None):
        self.page.url = "https://app.example.test/deep"
        return {
            "termination": "frontier_empty",
            "stats": {"actions": 3},
            "capabilities": [{"name": "Reports", "kind": "button", "url": "https://app.example.test/"}],
            "dangerous_controls": [{"name": "Delete account", "clicked": False}],
        }

    monkeypatch.setattr(ExplorationAgent, "run", fake_run)
    engine = _engine()
    engine._emit = emitter
    page = FakePage("https://app.example.test/")

    result = await engine._run_agent_exploration(page)

    assert result is not None
    assert result["termination"] == "frontier_empty"
    assert page.goto_calls == ["https://app.example.test/"]
    assert [name for name, _ in events] == [
        "exploration.agent.started",
        "exploration.agent.finished",
        "exploration.agent.capabilities",
    ]
    assert events[2][1]["dangerous_controls"][0]["name"] == "Delete account"
