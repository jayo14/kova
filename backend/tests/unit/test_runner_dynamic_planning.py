import uuid
from unittest.mock import MagicMock, PropertyMock, patch
import pytest

from app.engine.execution.runner import FlowRunner
from app.engine.browser.session import BrowserSession
from app.engine.ai.schemas import JourneyPlan, ProposedStep
from app.engine.ai.settings import AISettings


@pytest.mark.asyncio
async def test_runner_dynamic_journey_planning_when_steps_empty():
    """Verify runner dynamically plans actions when flow_steps is empty but objective is set."""
    runner = FlowRunner()
    mock_plan = JourneyPlan(
        objective="Practice Quiz",
        intent="practice_quiz",
        steps=[
            ProposedStep(
                action="wait",
                description="Wait for quiz elements",
                target={"css": "body"},
            )
        ],
        success_condition={"text_visible": "Quiz Completed"},
        confidence=0.9,
    )

    with patch("app.engine.execution.runner.publish_frame", return_value=None):
        with patch.object(BrowserSession, "navigate", return_value=None):
            with patch.object(BrowserSession, "close", return_value=None):
                with patch("app.engine.ai.reasoner.AgentReasoner.plan_journey", return_value=mock_plan):
                    with patch.object(AISettings, "ai_enabled", new_callable=PropertyMock, return_value=True):
                        with patch("app.engine.ai.provider.get_ai_provider", return_value=MagicMock()):
                            result = await runner.execute(
                                execution_id=uuid.uuid4(),
                                flow_steps=[],
                                target_url="https://example.com/quiz",
                                objective="Practice Quiz",
                                success_condition=None,
                            )
                            assert result is not None
                            assert "events" in result
