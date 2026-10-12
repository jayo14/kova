import pytest

from app.modules.executions.repository import ExecutionRepository
from app.modules.flows.repository import FlowRepository
from app.modules.projects.repository import ProjectRepository


@pytest.mark.asyncio
async def test_execution_keeps_immutable_flow_version_snapshot(db_session):
    project = await ProjectRepository(db_session).create(name="Snapshot", base_url="https://app.example")
    flows = FlowRepository(db_session)
    flow = await flows.create(
        project_id=project.id,
        name="Create record",
        objective="A record appears",
        steps=[{"action": "click", "selector": "button#create"}],
        success_condition={"text_visible": "Created"},
        preconditions={"auth_verified": True},
    )
    snapshot = {
        "version": flow.version,
        "name": flow.name,
        "objective": flow.objective,
        "steps": flow.steps,
        "success_condition": flow.success_condition,
        "preconditions": flow.preconditions,
        "target_url": project.base_url,
    }
    execution = await ExecutionRepository(db_session).create(flow.id, flow_version=flow.version, flow_snapshot=snapshot)
    await flows.update(flow.id, steps=[{"action": "click", "selector": "button#new"}])

    assert execution.flow_version == 1
    assert execution.flow_snapshot["steps"] == [{"action": "click", "selector": "button#create"}]
    assert execution.flow_snapshot["preconditions"] == {"auth_verified": True}
    assert flow.version == 2


@pytest.mark.asyncio
async def test_flow_version_changes_only_when_definition_changes(db_session):
    project = await ProjectRepository(db_session).create(name="Version", base_url="https://app.example")
    flows = FlowRepository(db_session)
    flow = await flows.create(project_id=project.id, name="Flow")
    await flows.update(flow.id)
    assert flow.version == 1
    await flows.update(flow.id, name="Renamed")
    assert flow.version == 2
