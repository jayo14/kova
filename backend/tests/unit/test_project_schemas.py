import pytest

from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


def test_project_create_schema():
    data = ProjectCreate(name="Test Project", base_url="http://localhost")
    assert data.name == "Test Project"
    assert data.base_url == "http://localhost"
    assert data.description is None


def test_project_create_schema_with_description():
    data = ProjectCreate(
        name="Test Project",
        base_url="http://localhost",
        description="A test",
    )
    assert data.description == "A test"


def test_project_update_schema_partial():
    data = ProjectUpdate(name="Updated")
    assert data.name == "Updated"
    assert data.base_url is None


def test_project_update_schema_empty():
    data = ProjectUpdate()
    assert data.name is None
    assert data.base_url is None
