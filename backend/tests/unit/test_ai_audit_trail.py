import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.engine.browser.auth import (
    find_submit_button,
    find_auth_entrance_semantically,
    find_auth_inputs_semantically,
    perform_login,
)
from app.engine.exploration.discovery.ai_assistant import AIAssistant
from app.modules.executions.event_types import EventTypes
from app.modules.product_graph.schemas import Action


@pytest.mark.asyncio
async def test_find_submit_button_emits_ai_proposal_and_assisted():
    """Verify find_submit_button emits AI_PROPOSAL and AI_ASSISTED when AI proposes selector."""
    mock_page = AsyncMock()
    # No semantic submit selectors match
    mock_page.locator = MagicMock(return_value=AsyncMock(count=AsyncMock(return_value=0)))

    # Mock locator for the proposed button
    mock_btn = AsyncMock()
    mock_btn.is_visible = AsyncMock(return_value=True)

    def mock_page_locator(sel):
        if sel == "button#login-submit":
            return MagicMock(first=mock_btn)
        return MagicMock(first=AsyncMock(is_visible=AsyncMock(return_value=False)), count=AsyncMock(return_value=0))

    mock_page.locator = mock_page_locator
    mock_page.observe = AsyncMock(return_value={"elements": []})

    events = []

    def mock_recorder(etype, edata):
        events.append((etype, edata))

    # Mock reasoner proposal
    with pytest.MonkeyPatch.context() as mp:
        from app.engine.ai.settings import AISettings
        mp.setattr(AISettings, "ai_enabled", property(lambda self: True))


        mock_provider = MagicMock()
        mp.setattr("app.engine.ai.provider.get_ai_provider", lambda: mock_provider)

        mock_reasoner = MagicMock()
        mock_reasoner.propose_submit_button = AsyncMock(return_value="button#login-submit")
        mp.setattr("app.engine.ai.reasoner.AgentReasoner", lambda p: mock_reasoner)

        btn = await find_submit_button(mock_page, event_recorder=mock_recorder)
        assert btn is not None

    types = [e[0] for e in events]
    assert EventTypes.AI_PROPOSAL in types
    assert EventTypes.AI_ASSISTED in types

    proposal_payload = next(e[1] for e in events if e[0] == EventTypes.AI_PROPOSAL)
    assert proposal_payload["stage"] == "submit_button"
    assert proposal_payload["selector"] == "button#login-submit"
    assert proposal_payload["accepted"] is True


@pytest.mark.asyncio
async def test_find_auth_entrance_emits_sanitized_ai_events():
    """Verify find_auth_entrance_semantically emits AI_PROPOSAL and AI_ASSISTED."""
    mock_page = AsyncMock()
    mock_page.url = "http://localhost:3000"
    mock_page.evaluate = AsyncMock(return_value=[
        {"index": 0, "tagName": "a", "text": "Log In", "href": "/login", "role": "link", "ariaLabel": ""},
    ])
    mock_btn = AsyncMock()
    mock_btn.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=MagicMock(first=mock_btn))

    mock_provider = MagicMock()
    mock_result = MagicMock(entrance_index=0)

    events = []

    def mock_recorder(etype, edata):
        events.append((etype, edata))

    with pytest.MonkeyPatch.context() as mp:
        mock_reasoner = MagicMock()
        mock_reasoner.identify_auth_entrance = AsyncMock(return_value=mock_result)
        mp.setattr("app.engine.ai.reasoner.AgentReasoner", lambda p: mock_reasoner)

        res = await find_auth_entrance_semantically(
            mock_page,
            provider=mock_provider,
            is_signup=False,
            event_recorder=mock_recorder,
        )
        assert res is True

    types = [e[0] for e in events]
    assert EventTypes.AI_PROPOSAL in types
    assert EventTypes.AI_ASSISTED in types

    proposal_data = next(e[1] for e in events if e[0] == EventTypes.AI_PROPOSAL)
    assert proposal_data["stage"] == "auth_entrance"
    assert proposal_data["entrance_index"] == 0
    # Invariant: no passwords in proposal
    assert "password" not in str(proposal_data).lower()


@pytest.mark.asyncio
async def test_ai_assistant_labels_sources_honestly():
    """Verify AIAssistant distinguishes heuristic fallback vs AI proposal."""
    # Without reasoner -> heuristic_inference
    assistant_h = AIAssistant(reasoner=None)
    action_h = Action(
        project_id=uuid.uuid4(),
        page_id=uuid.uuid4(),
        name="button_submit",
        selector="button#btn-sub",
        action_type="submit",
        confidence=0.3,
    )
    proposals_h = await assistant_h.assist_ambiguous_actions([action_h], {"url": "/app"})
    assert len(proposals_h) == 1
    assert action_h.source == "heuristic_inference"
    assert proposals_h[0].stage == "heuristic_action_extraction"

    # With reasoner -> ai_proposal
    assistant_ai = AIAssistant(reasoner=MagicMock())
    action_ai = Action(
        project_id=uuid.uuid4(),
        page_id=uuid.uuid4(),
        name="button_save",
        selector="button#btn-save",
        confidence=0.3,
    )
    proposals_ai = await assistant_ai.assist_ambiguous_actions([action_ai], {"url": "/app"})
    assert len(proposals_ai) == 1
    assert action_ai.source == "ai_proposal"
    assert proposals_ai[0].stage == "action_extraction"
