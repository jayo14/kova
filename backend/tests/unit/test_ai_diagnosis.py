"""Unit tests for AI failure diagnosis (§5 capability E)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import FailureHypothesis


@pytest.mark.asyncio
async def test_propose_failure_hypothesis_with_ai():
    mock_provider = MagicMock()
    mock_hypothesis = FailureHypothesis(
        root_cause="The backend rejected the request because the email format was invalid.",
        confidence=0.85,
        evidence_cited=["ev_123"],
        alternative_explanations=["Network timeout during submission"],
        recommended_investigation="Check email validation regex on the server endpoint.",
        reproduction_steps=["Navigate to form", "Submit invalid email", "Observe 422 Unprocessable Entity"],
    )
    mock_provider.generate_structured = AsyncMock(return_value=mock_hypothesis)

    reasoner = AgentReasoner(mock_provider)
    res = await reasoner.propose_failure_hypothesis(
        execution_id="exec_1",
        events=[{"type": "action.failed", "evidence_id": "ev_123"}],
        verification_checks=[{"name": "check_submit", "verdict": "failed", "reason": "Expected 200 got 422"}],
        evidence_summary={"screenshot_count": 1},
    )

    assert res is not None
    assert "email format" in res.root_cause
    assert res.confidence == 0.85
    assert res.evidence_cited == ["ev_123"]


@pytest.mark.asyncio
async def test_propose_failure_hypothesis_heuristic_fallback():
    # Provider is None -> heuristic fallback
    reasoner = AgentReasoner(provider=None)
    res = await reasoner.propose_failure_hypothesis(
        execution_id="exec_2",
        events=[],
        verification_checks=[
            {
                "name": "login_redirect",
                "verdict": "failed",
                "reason": "URL did not match /dashboard",
                "evidence_ids": ["ev_screenshot_1"],
            }
        ],
        evidence_summary={},
    )

    assert res is not None
    assert "login_redirect" in res.root_cause
    assert res.confidence == 0.5
    assert res.evidence_cited == ["ev_screenshot_1"]
    assert "Inspect the evidence" in res.recommended_investigation


@pytest.mark.asyncio
async def test_hypothesis_cites_evidence_ids():
    mock_provider = MagicMock()
    mock_hypothesis = FailureHypothesis(
        root_cause="Database constraint violated",
        confidence=0.9,
        evidence_cited=["ev_real_1"],
        alternative_explanations=[],
        recommended_investigation="Check DB migration",
        reproduction_steps=[],
    )
    mock_provider.generate_structured = AsyncMock(return_value=mock_hypothesis)

    reasoner = AgentReasoner(mock_provider)
    res = await reasoner.propose_failure_hypothesis(
        execution_id="exec_3",
        events=[{"type": "network.error", "evidence_id": "ev_real_1"}],
        verification_checks=[],
        evidence_summary={},
    )

    assert "ev_real_1" in res.evidence_cited


@pytest.mark.asyncio
async def test_hypothesis_does_not_invent_evidence():
    mock_provider = MagicMock()
    # Mock AI invents an evidence ID that does not exist in events or checks
    mock_hypothesis = FailureHypothesis(
        root_cause="Memory allocation error",
        confidence=0.8,
        evidence_cited=["ev_real_1", "ev_hallucinated_999"],
        alternative_explanations=[],
        recommended_investigation="Inspect memory metrics",
        reproduction_steps=[],
    )
    mock_provider.generate_structured = AsyncMock(return_value=mock_hypothesis)

    reasoner = AgentReasoner(mock_provider)
    res = await reasoner.propose_failure_hypothesis(
        execution_id="exec_4",
        events=[{"type": "action.failed", "evidence_id": "ev_real_1"}],
        verification_checks=[],
        evidence_summary={},
    )

    # Hallucinated evidence ID must be rejected by anti-hallucination filter
    assert "ev_real_1" in res.evidence_cited
    assert "ev_hallucinated_999" not in res.evidence_cited
