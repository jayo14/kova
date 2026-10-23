import uuid

import pytest

from app.engine.execution.runner import FlowRunner
from app.engine.execution.state import ExecutionState


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
