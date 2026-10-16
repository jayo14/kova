import pytest
from unittest.mock import AsyncMock
from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import (
    AuthPageClassification,
    SubmitButtonProposal,
    ProposedFlowList,
    ProposedFlow,
    ProposedFlowStep,
)


@pytest.mark.asyncio
async def test_classify_auth_page_uses_structured():
    mock_provider = AsyncMock()
    mock_provider.generate_structured.return_value = AuthPageClassification(
        kind="login",
        confidence=0.95,
        reasoning="Username and password fields observed",
    )
    reasoner = AgentReasoner(mock_provider)

    res = await reasoner.classify_auth_page({"text": "Sign in with your email"})
    assert res.kind == "login"
    assert res.confidence == 0.95
    mock_provider.generate_structured.assert_called_once()
    kwargs = mock_provider.generate_structured.call_args.kwargs
    assert "system" in kwargs
    assert "prompt" in kwargs
    assert kwargs["schema"] == AuthPageClassification


@pytest.mark.asyncio
async def test_propose_submit_button_uses_structured():
    mock_provider = AsyncMock()
    mock_provider.generate_structured.return_value = SubmitButtonProposal(
        selector="button[type='submit']",
        confidence=0.88,
        reasoning="Primary form submit button",
    )
    reasoner = AgentReasoner(mock_provider)

    selector = await reasoner.propose_submit_button({"elements": [{"role": "button", "name": "Submit"}]})
    assert selector == "button[type='submit']"
    mock_provider.generate_structured.assert_called_once()
    kwargs = mock_provider.generate_structured.call_args.kwargs
    assert kwargs["schema"] == SubmitButtonProposal


@pytest.mark.asyncio
async def test_propose_flows_uses_structured_and_caps_confidence():
    mock_provider = AsyncMock()
    mock_provider.generate_structured.return_value = ProposedFlowList(
        flows=[
            ProposedFlow(
                name="Enroll in Course",
                steps=[
                    ProposedFlowStep(action="navigate", target="/courses"),
                    ProposedFlowStep(action="click", target="button:has-text('Enroll')"),
                ],
                confidence=0.99,
                reasoning="Test enrollment flow",
            )
        ]
    )
    reasoner = AgentReasoner(mock_provider)

    flows = await reasoner.propose_flows("enroll", {"pages": ["/courses"]})
    assert len(flows) == 1
    assert flows[0]["name"] == "Enroll in Course"
    # Capped at <= 0.9 per safety rule
    assert flows[0]["confidence"] <= 0.9


@pytest.mark.asyncio
async def test_propose_flows_heuristic_fallback_valid_actions():
    reasoner = AgentReasoner(None)
    flows = await reasoner.propose_flows("checkout", {})
    assert len(flows) == 1
    steps = flows[0]["steps"]
    # Must NOT have invalid "assert" action
    actions = [s["action"] for s in steps]
    assert "assert" not in actions
    assert "navigate" in actions
    assert "wait" in actions
