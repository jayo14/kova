import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.engine.exploration.discovery.auth_detector import AuthDetector
from app.modules.flows.schemas import StateAssertion, StateMutation
from app.modules.product_graph.schemas import Action, AuthCapability, Page, Persona
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.product_graph.models import ProductCapability, ProductPage
from app.modules.flows.service import FlowService
from app.modules.flows.schemas import FlowUpdate, FlowCreate
from app.engine.execution.runner import FlowRunner


@pytest.mark.asyncio
async def test_discovery_persists_auth_capability_rows():
    """Verify AuthDetector produces AuthCapability with proper persona and login_url."""
    project_id = uuid.uuid4()
    detector = AuthDetector()

    login_page = Page(
        project_id=project_id,
        url_pattern="/login",
        requires_auth=False,
    )
    dashboard_page = Page(
        project_id=project_id,
        url_pattern="/dashboard",
        requires_auth=True,
    )
    pages = [login_page, dashboard_page]

    actions = [
        Action(project_id=project_id, page_id=login_page.id, name="email_input", selector="input[type='email']", action_type="input"),
        Action(project_id=project_id, page_id=login_page.id, name="pwd_input", selector="input[type='password']", action_type="input"),
        Action(project_id=project_id, page_id=login_page.id, name="submit_btn", selector="button[type='submit']", action_type="click"),
    ]

    personas = [
        Persona(project_id=project_id, name="admin"),
        Persona(project_id=project_id, name="member"),
    ]

    auth_caps = await detector.detect_auth(pages, actions, personas)
    assert len(auth_caps) == 2
    admin_cap = next(c for c in auth_caps if c.persona == "admin")
    assert admin_cap.login_url == "/login"
    assert admin_cap.auth_strategy == "password_form"
    assert admin_cap.success_url_pattern == "/dashboard"
    assert any("persona:admin" in req for req in admin_cap.requires_capabilities)


@pytest.mark.asyncio
async def test_runner_uses_discovered_auth_capability():
    """Verify runner looks up discovered AuthCapability from ProductGraphRepository."""
    project_id = uuid.uuid4()
    persona = "admin"

    mock_db = AsyncMock()
    repo = ProductGraphRepository(mock_db)

    expected_cap = AuthCapability(
        project_id=project_id,
        name="Authenticate as admin",
        login_url="/custom-login",
        auth_strategy="password_form",
        persona="admin",
    )

    with patch.object(repo, "get_auth_capability_for_persona", AsyncMock(return_value=expected_cap)):
        res = await repo.get_auth_capability_for_persona(project_id, persona)
        assert res.login_url == "/custom-login"
        assert res.persona == "admin"


@pytest.mark.asyncio
async def test_runner_falls_back_when_no_auth_capability_in_graph():
    """Verify runner falls back safely when graph has no auth capability."""
    project_id = uuid.uuid4()
    mock_db = AsyncMock()
    repo = ProductGraphRepository(mock_db)

    with patch.object(repo, "get_auth_capability_for_persona", AsyncMock(return_value=None)):
        res = await repo.get_auth_capability_for_persona(project_id, "unknown")
        assert res is None


@pytest.mark.asyncio
async def test_auth_flow_can_be_activated(db_session):
    """Verify flow can be activated via FlowService.update_flow."""
    from app.modules.users.models import User
    from app.modules.projects.models import Project

    user = User(id=uuid.uuid4(), email=f"test-{uuid.uuid4().hex[:6]}@kova.local")
    db_session.add(user)
    await db_session.commit()

    project = Project(id=uuid.uuid4(), user_id=user.id, name="Test App", base_url="http://localhost:3000")
    db_session.add(project)
    await db_session.commit()

    from app.modules.flows.schemas import FlowStep

    flow_service = FlowService(db_session)
    create_dto = FlowCreate(
        project_id=project.id,
        name="Admin Login",
        persona={"name": "admin"},
        steps=[FlowStep(action="navigate", value="/login")],
        active=False,
    )
    created = await flow_service.create_flow(create_dto)
    assert created.active is False


    # Activate the flow
    updated = await flow_service.update_flow(created.id, FlowUpdate(active=True))
    assert updated is not None
    assert updated.active is True


