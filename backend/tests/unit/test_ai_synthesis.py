import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.engine.ai.provider import AIProvider, AIProviderError, TaskType
from app.engine.ai.reasoner import AgentReasoner
from app.engine.ai.schemas import AIGeneratedJourney, AIGeneratedJourneyList
from app.engine.exploration.explorer import ExplorationEngine


@pytest.mark.asyncio
async def test_synthesize_journeys_calls_mocked_provider():
    mock_provider = MagicMock(spec=AIProvider)
    expected_journeys = AIGeneratedJourneyList(
        journeys=[
            AIGeneratedJourney(
                name="test_checkout",
                title="Complete Product Checkout",
                description="User adds item and checks out",
                objective="Verify order is placed",
                category="workflow",
                kind="write_workflow",
                journey=["Add item to cart", "Proceed to checkout", "Submit order"],
                steps=[{"action": "click", "target": "Checkout"}],
                success_condition={"text_visible": "Order confirmed"},
                confidence=0.95,
                recommended=True,
                expected_outcome="Order confirmed",
                preconditions=[],
                control_hints=["Checkout"],
                risk_level="read-only",
            )
        ],
        recommendation_reason="Core transactional flow",
    )
    mock_provider.generate_structured = AsyncMock(return_value=expected_journeys)

    reasoner = AgentReasoner(mock_provider)
    result = await reasoner.synthesize_journeys(
        base_url="https://example.com",
        title="Example Store",
        goal="Test purchases",
        persona="Shopper",
        routes=[{"path": "/cart", "category": "feature"}],
        site_map=[{"url": "https://example.com/cart", "forms": [], "primary_actions": [], "interactive_elements": []}],
        capabilities=[{"name": "cart", "kind": "write_workflow"}],
    )

    assert result is not None
    assert len(result.journeys) == 1
    assert result.journeys[0].name == "test_checkout"
    mock_provider.generate_structured.assert_called_once()
    call_args = mock_provider.generate_structured.call_args
    assert call_args.kwargs.get("task_type") == TaskType.JOURNEY_SYNTHESIS


@pytest.mark.asyncio
async def test_synthesize_journeys_raises_on_provider_error():
    mock_provider = MagicMock(spec=AIProvider)
    mock_provider.generate_structured = AsyncMock(side_effect=AIProviderError("Model quota exceeded", provider="mock"))

    reasoner = AgentReasoner(mock_provider)
    with pytest.raises(AIProviderError) as exc_info:
        await reasoner.synthesize_journeys(
            base_url="https://example.com",
            title="Example Store",
            goal=None,
            persona="User",
        )
    assert "Model quota exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_explorer_emits_ai_synthesis_failed_on_error():
    emitted_events = []

    async def mock_event_emitter(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    engine = ExplorationEngine(
        exploration_id="00000000-0000-0000-0000-000000000001",
        url="https://example.com",
        event_emitter=mock_event_emitter,
    )

    mock_provider = MagicMock(spec=AIProvider)
    mock_provider.generate_structured = AsyncMock(side_effect=AIProviderError("Simulated LLM 503", provider="mock"))

    mock_page = MagicMock()
    mock_page.url = "https://example.com/dashboard"

    observation = {
        "title": "Example Dashboard",
        "elements": [
            {"type": "button", "name": "Submit Order", "text": "Submit Order"},
            {"type": "button", "name": "Add to Cart", "text": "Add to Cart"},
        ],
        "links": [{"href": "/dashboard/settings", "text": "Settings"}],
    }

    engine._analyze_routes = AsyncMock(return_value=[
        {"path": "/dashboard", "category": "feature", "accessible": True, "title": "Dashboard"}
    ])

    with patch("app.engine.exploration.explorer.get_ai_provider", return_value=mock_provider):
        discoveries, missions = await engine._discover_workflows(
            page=mock_page,
            observation=observation,
            selected_role="user",
            agent_capabilities=[],
        )

    # Must fall back to heuristic missions without crashing
    assert isinstance(missions, list)
    # Must emit ai_synthesis_failed event with reason and traceback
    failed_events = [payload for ev_type, payload in emitted_events if ev_type == "ai_synthesis_failed"]
    assert len(failed_events) >= 1
    assert "Simulated LLM 503" in failed_events[0]["error"]
    assert failed_events[0]["traceback"] != ""
