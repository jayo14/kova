import uuid
import pytest
from unittest.mock import AsyncMock

from app.engine.exploration.explorer import ExplorationEngine
from app.engine.exploration.discovery.persona_detector import PersonaDetector
from app.modules.product_graph.schemas import Page


class MockPage:
    def __init__(self, url="https://example.com", dom_roles=None, page_links=None):
        self.url = url
        self._dom_roles = dom_roles or []
        self._page_links = page_links or []

    async def evaluate(self, script, *args):
        return self._dom_roles


@pytest.mark.asyncio
async def test_loose_text_does_not_trigger_roles():
    """Text mentioning 'creator', 'teacher', or 'student' must NEVER trigger role options."""
    engine = ExplorationEngine(url="https://github.com", exploration_id=uuid.uuid4())
    page = MockPage("https://github.com", dom_roles=[], page_links=[])

    # Simulate page with marketing copy mentioning roles
    observation = {
        "title": "GitHub: Let's build from here",
        "text": "Join the world of creators, teachers, students, and software developers building on GitHub.",
        "elements": [
            {"type": "a", "name": "Explore", "selector": "a.explore"},
            {"type": "a", "name": "Sign up", "selector": "a.signup"},
        ],
    }

    roles = await engine._detect_roles(page, observation)
    assert roles == [], "Loose text mentions should not generate hallucinated role options"


@pytest.mark.asyncio
async def test_multi_namespace_triggers_workspace_question():
    """Detecting multiple distinct namespaces (/admin, /app) prompts for workspace selection."""
    engine = ExplorationEngine(url="https://saas-platform.com", exploration_id=uuid.uuid4())

    mock_links = [
        {"href": "/admin/users", "path": "/admin/users", "text": "Admin Console", "is_button": False},
        {"href": "/app/dashboard", "path": "/app/dashboard", "text": "App Workspace", "is_button": False},
        {"href": "/pricing", "path": "/pricing", "text": "Pricing", "is_button": False},
    ]

    page = MockPage("https://saas-platform.com", dom_roles=[])
    # Mock _extract_page_links to return our candidate namespace links
    engine._extract_page_links = AsyncMock(return_value=mock_links)

    observation = {
        "title": "SaaS Platform",
        "elements": [],
    }

    roles = await engine._detect_roles(page, observation)
    assert len(roles) >= 2
    role_ids = {r["id"] for r in roles}
    assert "admin" in role_ids
    assert "app" in role_ids
    assert "visitor" in role_ids, "Should include a public surface fallback option"


@pytest.mark.asyncio
async def test_dom_role_select_dropdown_detection():
    """Explicit <select name='role'> options in DOM generate precise grounded options."""
    engine = ExplorationEngine(url="https://marketplace.com", exploration_id=uuid.uuid4())

    dom_roles = [
        {
            "id": "buyer",
            "label": "Buyer / Shopper",
            "description": "Role option from role selector",
            "icon": "person",
            "source": "select",
        },
        {
            "id": "seller",
            "label": "Seller / Merchant",
            "description": "Role option from role selector",
            "icon": "person",
            "source": "select",
        },
    ]

    page = MockPage("https://marketplace.com", dom_roles=dom_roles)
    engine._extract_page_links = AsyncMock(return_value=[])

    observation = {"title": "Two-Sided Marketplace", "elements": []}
    roles = await engine._detect_roles(page, observation)

    assert len(roles) >= 2
    role_ids = {r["id"] for r in roles}
    assert "buyer" in role_ids
    assert "seller" in role_ids


def test_github_platform_detected_as_developer():
    """Technical routes on GitHub detect Developer and Visitor personas, never EdTech roles."""
    engine = ExplorationEngine(url="https://github.com", exploration_id=uuid.uuid4())
    route_map = [
        {"path": "/features/code-review", "category": "feature"},
        {"path": "/apps/desktop", "category": "feature"},
        {"path": "/features/ai/copilot", "category": "feature"},
        {"path": "/pricing", "category": "navigation"},
    ]

    personas = engine._detect_personas(route_map)
    assert "developer" in personas
    assert "visitor" in personas
    assert "creator" not in personas
    assert "student" not in personas
    assert "instructor" not in personas


def test_prioritize_routes_elevates_selected_role():
    """Selecting 'admin' role prioritizes /admin routes ahead of generic dashboards."""
    engine = ExplorationEngine(url="https://app.local", exploration_id=uuid.uuid4())
    routes = [
        {"path": "/app/feed", "text": "Feed"},
        {"path": "/admin/audit-logs", "text": "Audit Logs"},
        {"path": "/help", "text": "Help Center"},
    ]

    prioritized = engine._prioritize_routes(routes, selected_role="admin")
    assert prioritized[0]["path"] == "/admin/audit-logs"


@pytest.mark.asyncio
async def test_persona_detector_route_boundaries():
    """PersonaDetector detects roles only with proper path boundaries."""
    proj_id = uuid.uuid4()
    detector = PersonaDetector(project_id=proj_id)
    pages = [
        Page(project_id=proj_id, url_pattern="/admin/settings", title="Admin Settings"),
        Page(project_id=proj_id, url_pattern="/seller/orders", title="Seller Orders"),
        Page(project_id=proj_id, url_pattern="/blog/students-today", title="Blog article"), # substring match should not trigger student
    ]

    personas = await detector.detect_personas(browser_page=None, pages=pages)
    persona_names = {p.name for p in personas}

    assert "admin" in persona_names
    assert "seller" in persona_names
    assert "student" not in persona_names, "Blog article with student in slug should not trigger Student persona"
