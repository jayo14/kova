"""Unit tests for Feature 2: agent cost controls and loop protection."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.ai.executor import (
    AgentExecutor,
    AgentOutcome,
    MAX_MODEL_CALLS_PER_RUN,
    MAX_TOKENS_PER_RUN,
    LOOP_PROTECTION_REPEAT_LIMIT,
)
from app.engine.ai.memory import AgentMemory
from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import ActionProposal


class CountingProvider:
    """Provider that counts calls and reports token usage."""

    def __init__(self, fail_after: int | None = None):
        self.calls = 0
        self.fail_after = fail_after

    @property
    def name(self):
        return "counting"

    @property
    def model_name(self):
        return "counting"

    def get_usage(self):
        return {"total_tokens": self.calls * 100, "model_calls": self.calls}

    async def generate_structured(self, system, prompt, schema):
        self.calls += 1
        if self.fail_after is not None and self.calls >= self.fail_after:
            from app.engine.ai.provider import AIProviderError
            raise AIProviderError("provider down", provider=self.name)
        schema_name = getattr(schema, "__name__", str(schema))
        if schema_name == "GoalInterpretation":
            return schema(
                goal="Do something", domain="unknown", intent="do_something",
                success_requirements=[], needs_account=False, needs_email_capability=False,
                risk_level="low",
            )
        if schema_name == "JourneyPlan":
            return schema(
                objective="Do something", intent="do_something", steps=[],
                success_condition={}, confidence=0.5, risk_level="low",
            )
        return schema(action="observe", target={}, value="", reason="ok", expected_effect="ok")


def _make_executor(max_turns=60, provider=None):
    reasoner = AgentReasoner(provider=provider)
    return AgentExecutor(
        execution_id=__import__("uuid").uuid4(),
        reasoner=reasoner,
        email_provider=None,
        event_emitter=None,
        max_turns=max_turns,
        max_duration=None,
    )


def test_page_fingerprint_stable_and_sensitive():
    obs_a = {"url": "https://app.example.com/", "elements": [
        {"name": "Save", "type": "button"},
        {"name": "Cancel", "type": "button"},
    ]}
    obs_b = dict(obs_a)
    obs_c = {"url": "https://app.example.com/", "elements": [
        {"name": "Save", "type": "button"},
        {"name": "Delete", "type": "button"},
    ]}
    fp1 = AgentExecutor._page_fingerprint(obs_a)
    fp2 = AgentExecutor._page_fingerprint(dict(obs_a))
    fp3 = AgentExecutor._page_fingerprint(obs_b)
    fp4 = AgentExecutor._page_fingerprint(obs_c)
    assert fp1 == fp2 == fp3  # same state → same fingerprint
    assert fp4 != fp1  # different control → different fingerprint


def test_cost_cap_exceeded():
    provider = CountingProvider()
    exec_ = _make_executor(provider=provider, max_turns=200)

    memory = AgentMemory(execution_id="e1", objective="Do something")
    state = {"tick": 0}
    proposal = ActionProposal(action="observe", target={}, value="", reason="ok", expected_effect="ok")
    exec_.reasoner.propose_next_action = AsyncMock(return_value=proposal)

    mock_browser = MagicMock()
    mock_browser.page = MagicMock(url="https://app.example.com/")
    mock_browser.navigate = AsyncMock()

    def observe():
        state["tick"] += 1
        return {
            "url": "https://app.example.com/",
            "elements": [{"name": f"item-{state['tick']}", "type": "button"}],
            "text": f"tick {state['tick']}",
            "auth_signals": [],
        }
    mock_browser.observe = AsyncMock(side_effect=observe)

    outcome = _run_sync(exec_.run(mock_browser, "Do something", "https://app.example.com/"))
    assert outcome.status == "FAILED"
    assert outcome.failure_category == "cost_cap_exceeded"
    assert "cost cap" in outcome.reason


def test_loop_detected_stops_with_specific_reason():
    """Same page state + same action repeated LOOP_PROTECTION_REPEAT_LIMIT times → FAILED loop_detected."""
    provider = CountingProvider()
    exec_ = _make_executor(provider=provider, max_turns=20)

    # Same observation every turn → same fingerprint; reasoner always proposes the same click.
    observation = {
        "url": "https://app.example.com/",
        "elements": [{"name": "Reload", "type": "button"}],
        "text": "Same page",
        "auth_signals": [],
    }
    proposal = ActionProposal(
        action="observe", target={}, value="",
        reason="reload", expected_effect="page reloads",
    )

    reasoner = exec_.reasoner
    reasoner.propose_next_action = AsyncMock(return_value=proposal)

    mock_browser = MagicMock()
    mock_browser.page = MagicMock(url="https://app.example.com/")
    mock_browser.navigate = AsyncMock()
    mock_browser.observe = AsyncMock(return_value=observation)

    outcome = _run_sync(exec_.run(mock_browser, "Do something", "https://app.example.com/"))
    assert outcome.status == "FAILED"
    assert outcome.failure_category == "loop_detected"
    assert "Loop protection" in outcome.reason


def _run_sync(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_turn_budget_reports_cost():
    provider = CountingProvider()
    exec_ = _make_executor(provider=provider, max_turns=2)
    memory = AgentMemory(execution_id="e2", objective="Do something")
    observation = {"url": "https://app.example.com/", "elements": [], "text": "", "auth_signals": []}
    proposal = ActionProposal(action="observe", target={}, value="", reason="ok", expected_effect="ok")
    exec_.reasoner.propose_next_action = AsyncMock(return_value=proposal)
    mock_browser = MagicMock()
    mock_browser.page = MagicMock(url="https://app.example.com/")
    mock_browser.navigate = AsyncMock()
    mock_browser.observe = AsyncMock(return_value=observation)
    outcome = _run_sync(exec_.run(mock_browser, "Do something", "https://app.example.com/"))
    assert outcome.status == "UNVERIFIED"
    assert any("cost:" in f for f in outcome.facts), outcome.facts
