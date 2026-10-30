"""Unit tests for Feature 2: generic AI fallback replaces forgot-password state machine.

The fallback must NEVER silently run a benchmark-specific state machine on a real site.
When AI is unavailable it only takes safe generic steps (dismiss interstitials) or hands
back to the human (request_human).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.ai.memory import AgentMemory
from app.engine.ai.provider import AIProvider, AIProviderError
from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import ActionProposal, GoalInterpretation


class AlwaysFailingProvider(AIProvider):
    name = "failing"

    @property
    def model_name(self) -> str:
        return "failing"

    async def generate_structured(self, system, prompt, schema):
        raise AIProviderError("boom", provider=self.name)


class SucceedsOnRetryProvider(AIProvider):
    name = "retry"

    @property
    def model_name(self) -> str:
        return "retry"

    def __init__(self):
        self.calls = 0

    async def generate_structured(self, system, prompt, schema):
        self.calls += 1
        if self.calls == 1:
            raise AIProviderError("transient", provider=self.name)
        return schema(
            action="observe",
            target={},
            value="",
            reason="recovered",
            expected_effect="observed",
        )


def _interpretation():
    return GoalInterpretation(
        goal="Check profile",
        domain="unknown",
        intent="check_profile",
        success_requirements=[],
        needs_account=False,
        needs_email_capability=False,
        risk_level="low",
    )


def test_heuristic_fallback_requests_human_instead_of_forgot_password():
    """With AI unavailable, the fallback must NOT run a forgot-password flow."""
    reasoner = AgentReasoner(provider=None)
    memory = AgentMemory(execution_id="e1", objective="Reset my password")
    observation = {
        "buttons": [{"name": "Forgot password?", "type": "button"}],
        "links": [],
        "text_excerpt": "Forgot your password?",
        "inputs": [],
        "auth_signals": [],
    }
    proposal = reasoner._heuristic_next_action(memory, _interpretation(), observation)
    # Must hand control back to human — never silently execute forgot-password steps.
    assert proposal.action == "request_human"
    assert "unavailable" in proposal.reason.lower()


def test_heuristic_fallback_dismisses_consent_interstitial():
    reasoner = AgentReasoner(provider=None)
    memory = AgentMemory(execution_id="e2", objective="Buy item")
    observation = {
        "buttons": [{"name": "Accept all cookies", "type": "button"}],
        "links": [],
        "text_excerpt": "We use cookies",
        "dialogs": ["cookie banner"],
        "inputs": [],
        "auth_signals": [],
    }
    proposal = reasoner._heuristic_next_action(memory, _interpretation(), observation)
    assert proposal.action == "click"
    assert "cookie" in proposal.reason.lower() or "consent" in proposal.reason.lower() or "interstitial" in proposal.reason.lower()


@pytest.mark.asyncio
async def test_propose_next_action_retries_then_falls_back():
    """AI failure → retry with backoff → generic fallback (not forgot-password flow)."""
    reasoner = AgentReasoner(provider=AlwaysFailingProvider())
    memory = AgentMemory(execution_id="e3", objective="Check profile")
    observation = {"buttons": [], "links": [], "text_excerpt": "Hello", "inputs": [], "auth_signals": []}
    proposal = await reasoner.propose_next_action(memory, _interpretation(), observation)
    assert proposal.action == "request_human"


@pytest.mark.asyncio
async def test_propose_next_action_succeeds_on_retry():
    """Transient AI failure retries and recovers."""
    prov = SucceedsOnRetryProvider()
    reasoner = AgentReasoner(provider=prov)
    memory = AgentMemory(execution_id="e4", objective="Check profile")
    observation = {"buttons": [], "links": [], "text_excerpt": "Hello", "inputs": [], "auth_signals": []}
    proposal = await reasoner.propose_next_action(memory, _interpretation(), observation)
    assert prov.calls == 2
    assert proposal.action == "observe"
    assert proposal.reason == "recovered"
