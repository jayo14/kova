import uuid

import pytest

from app.modules.flows.repository import FlowRepository
from app.modules.projects.repository import ProjectRepository


@pytest.fixture
async def project(db_session):
    repo = ProjectRepository(db_session)
    return await repo.create(name="TestProject", base_url="http://localhost")


@pytest.mark.asyncio
async def test_create_flow(db_session, project):
    repo = FlowRepository(db_session)
    flow = await repo.create(
        project_id=project.id,
        name="TestFlow",
        steps=[{"action": "click", "selector": "#btn"}],
    )
    assert flow.name == "TestFlow"
    assert flow.project_id == project.id
    assert len(flow.steps) == 1


@pytest.mark.asyncio
async def test_create_flow_with_persona(db_session, project):
    repo = FlowRepository(db_session)
    flow = await repo.create(
        project_id=project.id,
        name="TestFlow",
        persona={"role": "tester", "style": "aggressive"},
        objective="Login and verify dashboard",
        success_condition={"url_contains": "/dashboard"},
    )
    assert flow.persona == {"role": "tester", "style": "aggressive"}
    assert flow.objective == "Login and verify dashboard"
    assert flow.success_condition == {"url_contains": "/dashboard"}


@pytest.mark.asyncio
async def test_get_flow_by_id(db_session, project):
    repo = FlowRepository(db_session)
    flow = await repo.create(project_id=project.id, name="TestFlow")
    found = await repo.get_by_id(flow.id)
    assert found is not None
    assert found.name == "TestFlow"


@pytest.mark.asyncio
async def test_list_flows_by_project(db_session, project):
    repo = FlowRepository(db_session)
    await repo.create(project_id=project.id, name="A")
    await repo.create(project_id=project.id, name="B")
    flows = await repo.list_by_project(project.id)
    assert len(flows) == 2


@pytest.mark.asyncio
async def test_update_flow(db_session, project):
    repo = FlowRepository(db_session)
    flow = await repo.create(project_id=project.id, name="Old")
    updated = await repo.update(flow.id, name="New", objective="Updated objective")
    assert updated.name == "New"
    assert updated.objective == "Updated objective"


@pytest.mark.asyncio
async def test_delete_flow(db_session, project):
    repo = FlowRepository(db_session)
    flow = await repo.create(project_id=project.id, name="ToDelete")
    deleted = await repo.delete(flow.id)
    assert deleted is True
    found = await repo.get_by_id(flow.id)
    assert found is None


@pytest.mark.asyncio
async def test_flow_state_contract_roundtrip(db_session, project):
    from app.modules.flows.schemas import FlowRead

    repo = FlowRepository(db_session)
    contract_data = {
        "requires": [{"key": "authenticated", "value": True, "predicate": "eq"}],
        "produces": [{"key": "enrolled:course_101", "value": True, "predicate": "eq"}],
        "consumes": ["course_seat"],
        "mutates": ["course_roster"],
        "reset_strategy": "create_new",
        "cost": 5,
        "persona": "student",
        "requires_credential": True,
    }
    flow = await repo.create(
        project_id=project.id,
        name="EnrollFlow",
        state_contract=contract_data,
    )
    assert flow.state_contract == contract_data

    found = await repo.get_by_id(flow.id)
    assert found is not None
    assert found.state_contract == contract_data

    flow_read = FlowRead.model_validate(found)
    assert flow_read.state_contract is not None
    assert len(flow_read.requires_state) == 1
    assert flow_read.requires_state[0].key == "authenticated"
    assert len(flow_read.produces_state) == 1
    assert flow_read.produces_state[0].key == "enrolled:course_101"
    assert flow_read.cost == 5
    assert flow_read.mutates_state == ["course_roster"]

    updated = await repo.update(flow.id, state_contract={"requires": [], "produces": [], "cost": 1})
    assert updated.state_contract == {"requires": [], "produces": [], "cost": 1}


@pytest.mark.asyncio
async def test_generated_flow_columns_roundtrip(db_session, project):
    from app.modules.flows.schemas import FlowRead

    repo = FlowRepository(db_session)
    json_repr = {
        "name": "Generated Checkout Flow",
        "steps": [{"action": "navigate", "value": "/checkout"}],
        "state_contract": {"requires": [], "produces": []},
        "source": "deterministic",
        "confidence": 0.95,
    }
    gherkin = 'Feature: Generated Checkout Flow\n  Scenario: Execute\n    Given the user navigates to "/checkout"\n'

    flow = await repo.create(
        project_id=project.id,
        name="Generated Checkout Flow",
        source="deterministic",
        confidence=0.95,
        active=False,
        json_repr=json_repr,
        gherkin_repr=gherkin,
    )
    assert flow.source == "deterministic"
    assert flow.confidence == 0.95
    assert flow.active is False
    assert flow.json_repr == json_repr
    assert flow.gherkin_repr == gherkin

    found = await repo.get_by_id(flow.id)
    assert found is not None
    assert found.source == "deterministic"
    assert found.confidence == 0.95
    assert found.active is False
    assert found.json_repr == json_repr
    assert found.gherkin_repr == gherkin

    flow_read = FlowRead.model_validate(found)
    assert flow_read.source == "deterministic"
    assert flow_read.confidence == 0.95
    assert flow_read.active is False
    assert flow_read.json_repr == json_repr
    assert flow_read.gherkin_repr == gherkin

    # Update active to True upon review
    updated = await repo.update(flow.id, active=True, confidence=1.0)
    assert updated.active is True
    assert updated.confidence == 1.0


@pytest.mark.asyncio
async def test_delete_flow_with_executions(db_session, project):
    from app.modules.executions.repository import ExecutionRepository

    flow_repo = FlowRepository(db_session)
    exec_repo = ExecutionRepository(db_session)

    flow = await flow_repo.create(project_id=project.id, name="FlowWithExecutions")
    execution = await exec_repo.create(flow_id=flow.id)
    assert execution is not None
    assert execution.flow_id == flow.id

    # Deleting the flow must succeed and cascade cleanly without not-null violations
    deleted = await flow_repo.delete(flow.id)
    assert deleted is True

    # Verify flow is gone
    assert await flow_repo.get_by_id(flow.id) is None
    # Verify execution is also deleted
    assert await exec_repo.get_by_id(execution.id) is None

