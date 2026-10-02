import uuid

import pytest

from app.modules.executions.event_model import ExecutionEvent
from app.modules.executions.models import ExecutionStatus
from app.modules.executions.repository import ExecutionEventRepository, ExecutionRepository
from app.modules.flows.repository import FlowRepository
from app.modules.projects.repository import ProjectRepository


@pytest.fixture
async def project(db_session):
    repo = ProjectRepository(db_session)
    return await repo.create(name="TestProject", base_url="http://localhost")


@pytest.fixture
async def flow(db_session, project):
    repo = FlowRepository(db_session)
    return await repo.create(project_id=project.id, name="TestFlow")


@pytest.fixture
async def execution(db_session, flow):
    repo = ExecutionRepository(db_session)
    return await repo.create(flow_id=flow.id)


@pytest.mark.asyncio
async def test_create_event(db_session, execution):
    repo = ExecutionEventRepository(db_session)
    event = await repo.create(
        execution_id=execution.id,
        event_type="navigate",
        payload={"url": "http://localhost"},
    )
    assert event.execution_id == execution.id
    assert event.event_type == "navigate"
    assert event.payload == {"url": "http://localhost"}


@pytest.mark.asyncio
async def test_list_events_by_execution(db_session, execution):
    repo = ExecutionEventRepository(db_session)
    await repo.create(execution_id=execution.id, event_type="navigate")
    await repo.create(execution_id=execution.id, event_type="click")
    events = await repo.list_by_execution(execution.id)
    assert len(events) == 2
    assert events[0].event_type == "navigate"
    assert events[1].event_type == "click"


@pytest.mark.asyncio
async def test_events_ordered_by_created_at(db_session, execution):
    repo = ExecutionEventRepository(db_session)
    await repo.create(execution_id=execution.id, event_type="first")
    await repo.create(execution_id=execution.id, event_type="second")
    events = await repo.list_by_execution(execution.id)
    assert events[0].created_at <= events[1].created_at


@pytest.mark.asyncio
async def test_delete_event(db_session, execution):
    repo = ExecutionEventRepository(db_session)
    event = await repo.create(execution_id=execution.id, event_type="test")
    await db_session.delete(event)
    await db_session.flush()
    events = await repo.list_by_execution(execution.id)
    assert len(events) == 0
