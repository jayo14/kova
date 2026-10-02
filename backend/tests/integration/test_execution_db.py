import uuid
from datetime import datetime, timezone

import pytest

from app.modules.executions.models import ExecutionStatus
from app.modules.executions.repository import ExecutionRepository
from app.modules.flows.repository import FlowRepository
from app.modules.projects.repository import ProjectRepository


@pytest.fixture
async def project(db_session):
    repo = ProjectRepository(db_session)
    return await repo.create(name="TestProject", base_url="http://localhost")


@pytest.fixture
async def flow(db_session, project):
    repo = FlowRepository(db_session)
    return await repo.create(
        project_id=project.id,
        name="TestFlow",
        steps=[{"action": "click", "selector": "#btn"}],
    )


@pytest.mark.asyncio
async def test_create_execution(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    assert execution.flow_id == flow.id
    assert execution.status == ExecutionStatus.CREATED.value


@pytest.mark.asyncio
async def test_get_execution_by_id(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    found = await repo.get_by_id(execution.id)
    assert found is not None
    assert found.status == ExecutionStatus.CREATED.value


@pytest.mark.asyncio
async def test_list_executions_by_flow(db_session, flow):
    repo = ExecutionRepository(db_session)
    await repo.create(flow_id=flow.id)
    await repo.create(flow_id=flow.id)
    executions = await repo.list_by_flow(flow.id)
    assert len(executions) == 2


@pytest.mark.asyncio
async def test_update_status_valid_transition(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    updated = await repo.update_status(execution.id, ExecutionStatus.QUEUED)
    assert updated.status == ExecutionStatus.QUEUED.value


@pytest.mark.asyncio
async def test_update_status_sets_started_at(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    await repo.update_status(execution.id, ExecutionStatus.QUEUED)
    await repo.update_status(execution.id, ExecutionStatus.INITIALIZING)
    await repo.update_status(execution.id, ExecutionStatus.BROWSER_READY)
    running = await repo.update_status(execution.id, ExecutionStatus.RUNNING)
    assert running.started_at is not None


@pytest.mark.asyncio
async def test_update_status_sets_completed_at(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    await repo.update_status(execution.id, ExecutionStatus.QUEUED)
    await repo.update_status(execution.id, ExecutionStatus.INITIALIZING)
    await repo.update_status(execution.id, ExecutionStatus.BROWSER_READY)
    await repo.update_status(execution.id, ExecutionStatus.RUNNING)
    completed = await repo.update_status(execution.id, ExecutionStatus.COMPLETED)
    assert completed.completed_at is not None


@pytest.mark.asyncio
async def test_update_status_sets_error_info(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    await repo.update_status(execution.id, ExecutionStatus.QUEUED)
    await repo.update_status(execution.id, ExecutionStatus.INITIALIZING)
    await repo.update_status(
        execution.id,
        ExecutionStatus.FAILED,
        error_code="BROWSER_ERROR",
        error_message="Failed to launch",
    )
    failed = await repo.get_by_id(execution.id)
    assert failed.error_code == "BROWSER_ERROR"
    assert failed.error_message == "Failed to launch"


@pytest.mark.asyncio
async def test_update_status_invalid_transition(db_session, flow):
    from app.modules.executions.state_machine import InvalidTransitionError

    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    with pytest.raises(InvalidTransitionError):
        await repo.update_status(execution.id, ExecutionStatus.RUNNING)


@pytest.mark.asyncio
async def test_full_lifecycle(db_session, flow):
    repo = ExecutionRepository(db_session)
    execution = await repo.create(flow_id=flow.id)
    await repo.update_status(execution.id, ExecutionStatus.QUEUED)
    await repo.update_status(execution.id, ExecutionStatus.INITIALIZING)
    await repo.update_status(execution.id, ExecutionStatus.BROWSER_READY)
    await repo.update_status(execution.id, ExecutionStatus.RUNNING)
    await repo.update_status(execution.id, ExecutionStatus.WAITING)
    await repo.update_status(execution.id, ExecutionStatus.RUNNING)
    final = await repo.update_status(execution.id, ExecutionStatus.COMPLETED)
    assert final.status == ExecutionStatus.COMPLETED.value
    assert final.started_at is not None
    assert final.completed_at is not None
