import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User


@pytest.fixture
async def user(db_session):
    u = User(id=uuid.uuid4(), email="project_db@example.com", name="Project DB User")
    db_session.add(u)
    await db_session.flush()
    return u


@pytest.mark.asyncio
async def test_create_project(db_session, user):
    repo = ProjectRepository(db_session)
    project = await repo.create(user.id, name="Test", base_url="http://localhost")
    assert project.name == "Test"
    assert project.base_url == "http://localhost"
    assert project.user_id == user.id
    assert project.id is not None


@pytest.mark.asyncio
async def test_get_project_by_id(db_session, user):
    repo = ProjectRepository(db_session)
    project = await repo.create(user.id, name="Test", base_url="http://localhost")
    found = await repo.get_by_id(project.id)
    assert found is not None
    assert found.name == "Test"


@pytest.mark.asyncio
async def test_get_project_not_found(db_session):
    repo = ProjectRepository(db_session)
    found = await repo.get_by_id(uuid.uuid4())
    assert found is None


@pytest.mark.asyncio
async def test_list_projects(db_session, user):
    repo = ProjectRepository(db_session)
    await repo.create(user.id, name="A", base_url="http://a.com")
    await repo.create(user.id, name="B", base_url="http://b.com")
    projects = await repo.list_by_user(user.id)
    assert len(projects) == 2


@pytest.mark.asyncio
async def test_update_project(db_session, user):
    repo = ProjectRepository(db_session)
    project = await repo.create(user.id, name="Old", base_url="http://old.com")
    updated = await repo.update(project.id, user.id, name="New", base_url="http://new.com")
    assert updated.name == "New"
    assert updated.base_url == "http://new.com"


@pytest.mark.asyncio
async def test_delete_project(db_session, user):
    repo = ProjectRepository(db_session)
    project = await repo.create(user.id, name="ToDelete", base_url="http://del.com")
    deleted = await repo.delete(project.id, user.id)
    assert deleted is True
    found = await repo.get_by_id(project.id)
    assert found is None


@pytest.mark.asyncio
async def test_delete_project_not_found(db_session, user):
    repo = ProjectRepository(db_session)
    deleted = await repo.delete(uuid.uuid4(), user.id)
    assert deleted is False


@pytest.mark.asyncio
async def test_project_with_extended_fields_persists_and_round_trips(db_session, user):
    repo = ProjectRepository(db_session)
    project = await repo.create(
        user.id,
        name="Extended Project",
        base_url="https://staging.example.com",
        description="A project with extended brief fields",
        product_goal="Verify sign up and purchase flows",
        env_config={"target": "staging", "allowed_hosts": ["staging.example.com"]},
        execution_limits={"max_duration_seconds": 600, "max_agent_turns": 40},
        safety_restrictions={"production_access_allowed": False, "payment_actions_allowed": False},
        browser_settings={"viewport_width": 1440, "viewport_height": 900},
    )
    found = await repo.get_by_id(project.id)
    assert found is not None
    assert found.product_goal == "Verify sign up and purchase flows"
    assert found.env_config["target"] == "staging"
    assert found.execution_limits["max_duration_seconds"] == 600
    assert found.safety_restrictions["production_access_allowed"] is False
    assert found.browser_settings["viewport_width"] == 1440


@pytest.mark.asyncio
async def test_runner_enforces_project_max_duration():
    from app.engine.execution.runner import FlowRunner
    from app.modules.projects.models import Project

    runner = FlowRunner()
    fake_project = Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Quick Project",
        base_url="http://localhost",
        execution_limits={"max_duration_seconds": 1},
        safety_restrictions={},
    )

    import asyncio

    async def _mock_execute_inner(*args, **kwargs):
        await asyncio.sleep(5)
        return {"success": True}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "_execute_inner", _mock_execute_inner)
        result = await runner.execute(
            execution_id=uuid.uuid4(),
            flow_steps=[],
            target_url="http://localhost",
            project=fake_project,
        )
        assert result["success"] is False
        assert "timed out after 1s" in result["error"]


@pytest.mark.asyncio
async def test_runner_blocks_production_navigation_when_not_allowed():
    from app.engine.execution.runner import FlowRunner, ExecutionError
    from app.modules.projects.models import Project

    runner = FlowRunner()
    fake_project = Project(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Safe Project",
        base_url="http://localhost",
        safety_restrictions={"production_access_allowed": False, "forbidden_routes": []},
    )

    from app.engine.execution.context import ExecutionContext
    from app.engine.execution.state import ExecutionState

    ctx = ExecutionContext(
        execution_id=str(uuid.uuid4()),
        target_url="http://localhost",
        state=ExecutionState.RUNNING,
        safety_restrictions=fake_project.safety_restrictions,
    )

    mock_browser = MagicMock()
    mock_browser.observe = AsyncMock(return_value={})

    with pytest.raises(ExecutionError, match="Production access not allowed"):
        await runner._execute_step(
            ctx,
            browser=mock_browser,
            action_executor=None,
            step={"type": "navigate", "url": "https://production.example.com/checkout"},
            step_index=0,
            event_recorder=None,
        )
