import asyncio
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


@pytest.mark.asyncio
async def test_explorer_chained_auth_mission_with_credentials(monkeypatch):
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://app.example.com",
        credential_id="cred-test-123",
    )
    class DummyPage:
        url = "https://app.example.com"

    mock_routes = [
        {"path": "/signup", "url": "https://app.example.com/signup", "accessible": True, "category": "auth", "has_form": True, "elements_count": 3, "text": "Sign Up", "title": "Sign Up"},
        {"path": "/login", "url": "https://app.example.com/login", "accessible": True, "category": "auth", "has_form": True, "elements_count": 3, "text": "Log In", "title": "Log In"},
    ]
    monkeypatch.setattr(explorer, "_analyze_routes", lambda page, url: asyncio.sleep(0, result=mock_routes))

    observation = {
        "title": "Example App",
        "elements": [
            {"type": "link", "name": "Sign Up"},
            {"type": "link", "name": "Log In"},
        ],
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), observation, "User")

    chained = next((m for m in missions if "Registration and Login" in m.name or "Chained" in m.name), None)
    assert chained is not None
    assert chained.category == "auth"
    assert "sign up, log in, and view account" in chained.objective.lower()
    assert len(chained.steps) > 5
    # Steps should reference the credential_id
    assert any(s.get("credential_id") == "cred-test-123" for s in chained.steps)
    assert chained.successCondition == {"auth_verified": {"auth_path": "/login"}}


@pytest.mark.asyncio
async def test_explorer_chained_auth_mission_needs_credentials(monkeypatch):
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://app.example.com",
    )
    class DummyPage:
        url = "https://app.example.com"

    mock_routes = [
        {"path": "/register", "url": "https://app.example.com/register", "accessible": True, "category": "auth", "has_form": True, "elements_count": 3, "text": "Register", "title": "Register"},
        {"path": "/signin", "url": "https://app.example.com/signin", "accessible": True, "category": "auth", "has_form": True, "elements_count": 3, "text": "Sign In", "title": "Sign In"},
    ]
    monkeypatch.setattr(explorer, "_analyze_routes", lambda page, url: asyncio.sleep(0, result=mock_routes))
    # Ensure temp mail is disabled
    monkeypatch.setattr("app.engine.email.get_temp_email_provider", lambda: None)

    observation = {
        "title": "Example App",
        "elements": [
            {"type": "link", "name": "Register"},
            {"type": "link", "name": "Sign In"},
        ],
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), observation, "User")

    chained = next((m for m in missions if "needs credentials" in m.name), None)
    assert chained is not None
    assert chained.steps == []
    assert chained.successCondition is None
    assert "credential" in chained.description.lower()


@pytest.mark.asyncio
async def test_explorer_chained_auth_mission_with_temp_mail(monkeypatch):
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://app.example.com",
    )
    class DummyPage:
        url = "https://app.example.com"

    mock_routes = [
        {"path": "/signup", "url": "https://app.example.com/signup", "accessible": True, "category": "auth", "has_form": True, "elements_count": 3, "text": "Sign Up", "title": "Sign Up"},
        {"path": "/login", "url": "https://app.example.com/login", "accessible": True, "category": "auth", "has_form": True, "elements_count": 3, "text": "Log In", "title": "Log In"},
    ]
    monkeypatch.setattr(explorer, "_analyze_routes", lambda page, url: asyncio.sleep(0, result=mock_routes))

    from app.engine.email.provider import MailboxHandle
    class DummyMailProvider:
        async def create_mailbox(self, hint=None):
            return MailboxHandle(mailbox_id="mb-1", address="temp-user@kova.test")

    monkeypatch.setattr("app.engine.email.get_temp_email_provider", lambda: DummyMailProvider())

    observation = {
        "title": "Example App",
        "elements": [
            {"type": "link", "name": "Sign Up"},
            {"type": "link", "name": "Log In"},
        ],
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), observation, "User")

    chained = next((m for m in missions if "Registration and Login" in m.name), None)
    assert chained is not None
    assert len(chained.steps) > 5
    # Steps should type the temp mailbox address
    assert any(s.get("value") == "temp-user@kova.test" for s in chained.steps)


@pytest.mark.asyncio
async def test_explorer_standalone_form_mission(monkeypatch):
    explorer = ExplorationEngine(
        exploration_id=uuid.uuid4(),
        url="https://app.example.com",
    )
    class DummyPage:
        url = "https://app.example.com"

    mock_routes = [
        {"path": "/contact", "url": "https://app.example.com/contact", "accessible": True, "category": "form", "has_form": True, "elements_count": 4, "text": "Contact", "title": "Contact Us"},
    ]
    monkeypatch.setattr(explorer, "_analyze_routes", lambda page, url: asyncio.sleep(0, result=mock_routes))

    observation = {
        "title": "Example App",
        "elements": [
            {"type": "link", "name": "Contact"},
            {"type": "button", "name": "Learn More"},
        ],
    }
    discoveries, missions = await explorer._discover_workflows(DummyPage(), observation, "User")

    form_mission = next((m for m in missions if m.category == "form"), None)
    assert form_mission is not None
    assert "submit contact form" in form_mission.name.lower()
    assert form_mission.objective == "Submit contact form, then expect confirmation and no failed request"
    assert form_mission.successCondition == {"text_visible": "Thank"}
    assert any(s.get("type") == "click" and "submit" in s.get("target", "").lower() for s in form_mission.steps)

