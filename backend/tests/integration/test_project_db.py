import uuid

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
