import pytest
import uuid
from app.engine.exploration.explorer import ExplorationEngine
from app.modules.exploration.models import ExplorationStatus


@pytest.mark.asyncio
async def test_explorer_detect_roles():
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="http://example.com",
    )
    observation = {
        "text": "Choose your workspace: Student or Lecturer",
        "elements": [
            {"type": "button", "name": "Student Login"},
            {"type": "button", "name": "Lecturer Portal"},
        ],
    }
    roles = await explorer._detect_roles(None, observation)
    role_ids = [r["id"] for r in roles]
    assert "student" in role_ids
    assert "lecturer" in role_ids


@pytest.mark.asyncio
async def test_explorer_goal_directed_workflow_discovery():
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://tastiq.app.vercel.app",
        goal="test quiz generation",
    )
    class DummyPage:
        url = "https://tastiq.app.vercel.app/dashboard"

    observation = {
        "title": "Tastiq",
        "elements": [
            {"type": "button", "name": "Materials"},
            {"type": "button", "name": "Quiz Generator"},
        ],
        "text": "Generate interactive quizzes from your study material",
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), observation, "Student")

    assert len(missions) >= 1
    # First mission should be the goal-directed mission
    assert missions[0].name == "test quiz generation"
    assert missions[0].recommended is True
    assert len(discoveries) >= 2
