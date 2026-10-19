"""Unit tests for AI report synthesis (§5 capability H)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import ReportSummary


@pytest.mark.asyncio
async def test_synthesize_report_summary_with_ai():
    mock_provider = MagicMock()
    mock_summary = ReportSummary(
        headline="Validation failed: 1 flow failed due to missing validation on email field",
        key_findings=["Authentication succeeded", "Contact form failed HTTP 500"],
        overall_assessment="Overall application functionality is largely healthy except for the contact endpoint.",
        confidence=0.9,
        recommended_next_steps=["Verify backend contact endpoint logs"],
    )
    mock_provider.generate_structured = AsyncMock(return_value=mock_summary)

    reasoner = AgentReasoner(mock_provider)
    summary = await reasoner.synthesize_report_summary({
        "overall_status": "failed",
        "results": [
            {"flow_name": "Contact Form", "status": "failed", "failure_reason": "HTTP 500"},
            {"flow_name": "User Auth", "status": "passed", "failure_reason": None},
        ],
        "duration_ms": 12000,
    })

    assert summary is not None
    assert "Validation failed" in summary.headline
    assert summary.confidence == 0.9
    assert len(summary.key_findings) == 2


@pytest.mark.asyncio
async def test_synthesize_report_summary_heuristic_fallback():
    reasoner = AgentReasoner(provider=None)
    summary = await reasoner.synthesize_report_summary({
        "overall_status": "passed",
        "results": [
            {"flow_name": "Sign In", "status": "passed", "failure_reason": None},
            {"flow_name": "Checkout", "status": "passed", "failure_reason": None},
        ],
        "duration_ms": 8000,
    })

    assert summary is not None
    assert "Validation passed: 2 passed, 0 failed, 2 total flows" == summary.headline
    assert summary.confidence == 0.7
    assert "Overall status: passed" in summary.key_findings


@pytest.mark.asyncio
async def test_summary_headline_includes_overall_status():
    reasoner = AgentReasoner(provider=None)
    summary = await reasoner.synthesize_report_summary({
        "overall_status": "failed",
        "results": [
            {"flow_name": "Flow 1", "status": "failed", "failure_reason": "Error"},
        ],
        "duration_ms": 1000,
    })

    assert "failed" in summary.headline.lower()


@pytest.mark.asyncio
async def test_summary_recommended_next_steps_are_actionable():
    reasoner = AgentReasoner(provider=None)
    summary = await reasoner.synthesize_report_summary({
        "overall_status": "failed",
        "results": [
            {"flow_name": "Checkout Flow", "status": "failed", "failure_reason": "Timeout"},
        ],
        "duration_ms": 3000,
    })

    assert len(summary.recommended_next_steps) > 0
    # Must be non-generic (specifically mentions the flow name)
    assert any("Checkout Flow" in step for step in summary.recommended_next_steps)
