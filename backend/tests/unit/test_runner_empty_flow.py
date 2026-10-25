import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState


def _build_mock_browser():
    mb = AsyncMock()
    mb.page = AsyncMock()
    mb.page.url = "https://example.com"
    mb.page.title = AsyncMock(return_value="Example App")
    mb.page.screenshot = AsyncMock(return_value=b"pngdata")
    mb.page.evaluate = AsyncMock(return_value="Page content")
    mb.page.on = MagicMock()
    mb.page.remove_listener = MagicMock()
    mb.page.is_closed = MagicMock(return_value=False)
    mb.page.context.cookies = AsyncMock(return_value=[])
    mb.page.context.add_cookies = AsyncMock()
    mb.get_dom_snapshot = AsyncMock(return_value="<html><body>Example</body></html>")
    mb.get_a11y_tree = AsyncMock(return_value={})
    mb.observe = AsyncMock(return_value={"url": "https://example.com", "interactive_elements": []})
    mb.network_errors = []
    mb.start = AsyncMock()
    mb.close = AsyncMock()
    mb.navigate = AsyncMock()
    mb.start_step_network_capture = MagicMock()
    mb.end_step_network_capture = MagicMock(return_value=[])
    mb.video_path = None
    mb.trace_path = None
    return mb


@pytest.mark.asyncio
async def test_empty_flow_without_autonomous_path_fails_fast_before_browser(monkeypatch):
    """Empty steps + no objective + agent/AI disabled -> FAILED/FLOW_NOT_RUNNABLE, no browser launch."""
    from app.config.settings import settings
    from app.engine.ai.settings import ai_settings
    from app.engine.browser import session as browser_session_mod

    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", False)
    monkeypatch.setattr(type(ai_settings), "ai_enabled", property(lambda self: False))

    browser_instantiated = []

    class _BrowserSpy:
        def __init__(self, *args, **kwargs):
            browser_instantiated.append(True)

    monkeypatch.setattr(browser_session_mod, "BrowserSession", _BrowserSpy)
    monkeypatch.setattr(
        "app.engine.execution.runner.BrowserSession", _BrowserSpy
    )

    event_types = []

    async def recorder(execution_id, event_type, payload):
        event_types.append(event_type)

    result = await FlowRunner().execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        target_url="https://app.test/",
        objective=None,
        event_recorder=recorder,
    )

    assert result["success"] is False
    assert result["error_code"] == "FLOW_NOT_RUNNABLE"
    assert result["failure_category"] == "flow_configuration"
    assert result["state"] == ExecutionState.FAILED.value
    assert browser_instantiated == []
    assert "execution.failed" in event_types
    assert "browser.started" not in event_types


@pytest.mark.asyncio
async def test_empty_flow_with_objective_but_no_agent_or_ai_fails_fast(monkeypatch):
    """Objective present but both autonomous paths disabled still fails fast."""
    from app.config.settings import settings
    from app.engine.ai.settings import ai_settings
    from app.engine.browser import session as browser_session_mod

    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", False)
    monkeypatch.setattr(type(ai_settings), "ai_enabled", property(lambda self: False))

    browser_instantiated = []

    class _BrowserSpy:
        def __init__(self, *args, **kwargs):
            browser_instantiated.append(True)

    monkeypatch.setattr(browser_session_mod, "BrowserSession", _BrowserSpy)
    monkeypatch.setattr("app.engine.execution.runner.BrowserSession", _BrowserSpy)

    result = await FlowRunner().execute(
        execution_id=uuid.uuid4(),
        flow_steps=[],
        target_url="https://app.test/",
        objective="log in and verify dashboard",
    )

    assert result["success"] is False
    assert result["error_code"] == "FLOW_NOT_RUNNABLE"
    assert browser_instantiated == []


@pytest.mark.asyncio
async def test_empty_flow_with_objective_and_provider_ai_passes_fail_fast(monkeypatch):
    """ai_enabled via a per-provider key (no AI_API_KEY) must unlock the autonomous path.

    The fail-fast must not fire; only after planning yields no steps should the run fail,
    and the message must be provider-agnostic.
    """
    from app.config.settings import settings
    from app.engine.ai.settings import ai_settings

    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", False)
    monkeypatch.setattr(type(ai_settings), "ai_enabled", property(lambda self: True))

    mock_browser = _build_mock_browser()
    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.ai.provider.get_ai_provider", return_value=None):
        result = await FlowRunner().execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="https://app.test/",
            objective="log in and verify dashboard",
        )

    assert mock_browser.start.await_count == 1, "browser must start (fail-fast passed)"
    assert result["success"] is False
    assert result["error_code"] == "FLOW_NOT_RUNNABLE"
    assert result["failure_category"] == "flow_configuration"
    assert "any provider key" in result["error"]
    assert "AGENT_EXECUTION_ENABLED" in result["error"]


@pytest.mark.asyncio
async def test_planning_provider_auth_failure_classified_as_misconfigured(monkeypatch):
    """A provider auth failure during dynamic planning must not be reported as flow_configuration."""
    from app.config.settings import settings
    from app.engine.ai.provider import AIProviderError
    from app.engine.ai.settings import ai_settings

    monkeypatch.setattr(settings, "AGENT_EXECUTION_ENABLED", False)
    monkeypatch.setattr(type(ai_settings), "ai_enabled", property(lambda self: True))

    mock_browser = _build_mock_browser()

    class _Reasoner:
        def __init__(self, provider=None):
            self.provider = provider

        async def interpret_goal(self, objective):
            return SimpleNamespace(goal=objective)

        async def plan_journey(self, memory, interpretation, obs, flag):
            raise AIProviderError("invalid api key", provider="gemini", status_code=401)

    from types import SimpleNamespace

    with patch("app.engine.execution.runner.BrowserSession", return_value=mock_browser), \
         patch("app.engine.execution.runner.publish_frame", return_value=None), \
         patch("app.engine.ai.provider.get_ai_provider", return_value=object()), \
         patch("app.engine.ai.reasoner.AgentReasoner", _Reasoner):
        result = await FlowRunner().execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="https://app.test/",
            objective="log in and verify dashboard",
        )

    assert result["success"] is False
    assert result["error_code"] == "AI_PROVIDER_MISCONFIGURED"
    assert result["failure_category"] == "ai_provider_misconfigured"
    assert "gemini" in result["error"]
