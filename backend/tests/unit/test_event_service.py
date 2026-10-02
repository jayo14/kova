import uuid

import pytest

from app.modules.executions.event_service import EventService
from app.modules.executions.event_types import EventTypes
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
    return await repo.create(project_id=project.id, name="TestFlow")


@pytest.fixture
async def execution(db_session, flow):
    repo = ExecutionRepository(db_session)
    return await repo.create(flow_id=flow.id)


@pytest.fixture
def event_service(db_session):
    return EventService(db_session)


@pytest.mark.asyncio
async def test_record_event(db_session, execution, event_service):
    event = await event_service.record_event(
        execution_id=execution.id,
        event_type=EventTypes.EXECUTION_CREATED,
        payload={"status": "created"},
    )
    assert event.execution_id == execution.id
    assert event.event_type == EventTypes.EXECUTION_CREATED
    assert event.payload == {"status": "created"}


@pytest.mark.asyncio
async def test_record_event_without_payload(db_session, execution, event_service):
    event = await event_service.record_event(
        execution_id=execution.id,
        event_type=EventTypes.BROWSER_STARTED,
    )
    assert event.payload == {}


@pytest.mark.asyncio
async def test_get_events_chronological_order(db_session, execution, event_service):
    await event_service.record_event(
        execution_id=execution.id,
        event_type=EventTypes.EXECUTION_CREATED,
    )
    await event_service.record_event(
        execution_id=execution.id,
        event_type=EventTypes.BROWSER_STARTED,
    )
    await event_service.record_event(
        execution_id=execution.id,
        event_type=EventTypes.PAGE_LOADED,
        payload={"url": "http://example.com"},
    )

    events = await event_service.get_events(execution.id)
    assert len(events) == 3
    assert events[0].event_type == EventTypes.EXECUTION_CREATED
    assert events[1].event_type == EventTypes.BROWSER_STARTED
    assert events[2].event_type == EventTypes.PAGE_LOADED
    assert events[0].created_at <= events[1].created_at <= events[2].created_at


@pytest.mark.asyncio
async def test_record_execution_created(db_session, execution, event_service):
    event = await event_service.record_execution_created(execution.id)
    assert event.event_type == EventTypes.EXECUTION_CREATED
    assert event.payload == {"status": "created"}


@pytest.mark.asyncio
async def test_record_execution_queued(db_session, execution, event_service):
    event = await event_service.record_execution_queued(execution.id)
    assert event.event_type == EventTypes.EXECUTION_QUEUED
    assert event.payload == {"status": "queued"}


@pytest.mark.asyncio
async def test_record_execution_started(db_session, execution, event_service):
    event = await event_service.record_execution_started(execution.id)
    assert event.event_type == EventTypes.EXECUTION_STARTED
    assert event.payload == {"status": "started"}


@pytest.mark.asyncio
async def test_record_browser_started(db_session, execution, event_service):
    event = await event_service.record_browser_started(execution.id)
    assert event.event_type == EventTypes.BROWSER_STARTED
    assert event.payload == {"browser": "chromium"}


@pytest.mark.asyncio
async def test_record_page_loaded(db_session, execution, event_service):
    event = await event_service.record_page_loaded(
        execution.id, url="http://example.com", title="Example"
    )
    assert event.event_type == EventTypes.PAGE_LOADED
    assert event.payload == {"url": "http://example.com", "title": "Example"}


@pytest.mark.asyncio
async def test_record_agent_observed(db_session, execution, event_service):
    observation = {"url": "http://example.com", "title": "Example", "elements": []}
    event = await event_service.record_agent_observed(execution.id, observation)
    assert event.event_type == EventTypes.AGENT_OBSERVED
    assert event.payload == observation


@pytest.mark.asyncio
async def test_record_action_started(db_session, execution, event_service):
    event = await event_service.record_action_started(
        execution.id, action="click", target="#submit-btn"
    )
    assert event.event_type == EventTypes.ACTION_STARTED
    assert event.payload == {"action": "click", "target": "#submit-btn"}


@pytest.mark.asyncio
async def test_record_action_completed(db_session, execution, event_service):
    event = await event_service.record_action_completed(
        execution.id, action="click", target="#submit-btn"
    )
    assert event.event_type == EventTypes.ACTION_COMPLETED
    assert event.payload == {"action": "click", "target": "#submit-btn"}


@pytest.mark.asyncio
async def test_record_verification_started(db_session, execution, event_service):
    event = await event_service.record_verification_started(execution.id)
    assert event.event_type == EventTypes.VERIFICATION_STARTED


@pytest.mark.asyncio
async def test_record_verification_passed(db_session, execution, event_service):
    checks = [{"type": "url_contains", "passed": True}]
    event = await event_service.record_verification_passed(execution.id, checks)
    assert event.event_type == EventTypes.VERIFICATION_PASSED
    assert event.payload == {"checks": checks}


@pytest.mark.asyncio
async def test_record_verification_failed(db_session, execution, event_service):
    checks = [{"type": "url_contains", "passed": False, "expected": "/dashboard"}]
    event = await event_service.record_verification_failed(execution.id, checks)
    assert event.event_type == EventTypes.VERIFICATION_FAILED
    assert event.payload == {"checks": checks}


@pytest.mark.asyncio
async def test_record_recovery_started(db_session, execution, event_service):
    event = await event_service.record_recovery_started(
        execution.id, reason="Page unresponsive"
    )
    assert event.event_type == EventTypes.RECOVERY_STARTED
    assert event.payload == {"reason": "Page unresponsive"}


@pytest.mark.asyncio
async def test_record_execution_completed(db_session, execution, event_service):
    event = await event_service.record_execution_completed(
        execution.id, result={"final_url": "http://example.com"}
    )
    assert event.event_type == EventTypes.EXECUTION_COMPLETED
    assert event.payload == {"result": {"final_url": "http://example.com"}}


@pytest.mark.asyncio
async def test_record_execution_completed_without_result(db_session, execution, event_service):
    event = await event_service.record_execution_completed(execution.id)
    assert event.event_type == EventTypes.EXECUTION_COMPLETED
    assert event.payload == {}


@pytest.mark.asyncio
async def test_record_execution_failed(db_session, execution, event_service):
    event = await event_service.record_execution_failed(
        execution.id, error_code="TIMEOUT", error_message="Page load timed out"
    )
    assert event.event_type == EventTypes.EXECUTION_FAILED
    assert event.payload == {
        "error_code": "TIMEOUT",
        "error_message": "Page load timed out",
    }


@pytest.mark.asyncio
async def test_record_execution_cancelled(db_session, execution, event_service):
    event = await event_service.record_execution_cancelled(execution.id)
    assert event.event_type == EventTypes.EXECUTION_CANCELLED
    assert event.payload == {"status": "cancelled"}


@pytest.mark.asyncio
async def test_full_lifecycle_events(db_session, execution, event_service):
    """Test recording a full execution lifecycle with all event types."""
    await event_service.record_execution_created(execution.id)
    await event_service.record_execution_queued(execution.id)
    await event_service.record_execution_started(execution.id)
    await event_service.record_browser_started(execution.id)
    await event_service.record_page_loaded(
        execution.id, url="http://example.com", title="Example"
    )
    await event_service.record_agent_observed(
        execution.id, {"url": "http://example.com", "elements": []}
    )
    await event_service.record_action_started(execution.id, "click", "#btn")
    await event_service.record_action_completed(execution.id, "click", "#btn")
    await event_service.record_verification_started(execution.id)
    await event_service.record_verification_passed(
        execution.id, [{"type": "element_visible", "passed": True}]
    )
    await event_service.record_execution_completed(execution.id)

    events = await event_service.get_events(execution.id)
    assert len(events) == 11

    event_types = [e.event_type for e in events]
    assert event_types == [
        EventTypes.EXECUTION_CREATED,
        EventTypes.EXECUTION_QUEUED,
        EventTypes.EXECUTION_STARTED,
        EventTypes.BROWSER_STARTED,
        EventTypes.PAGE_LOADED,
        EventTypes.AGENT_OBSERVED,
        EventTypes.ACTION_STARTED,
        EventTypes.ACTION_COMPLETED,
        EventTypes.VERIFICATION_STARTED,
        EventTypes.VERIFICATION_PASSED,
        EventTypes.EXECUTION_COMPLETED,
    ]


@pytest.mark.asyncio
async def test_failed_lifecycle_events(db_session, execution, event_service):
    """Test recording a failed execution lifecycle."""
    await event_service.record_execution_created(execution.id)
    await event_service.record_execution_started(execution.id)
    await event_service.record_browser_started(execution.id)
    await event_service.record_page_loaded(
        execution.id, url="http://example.com", title="Example"
    )
    await event_service.record_verification_started(execution.id)
    await event_service.record_verification_failed(
        execution.id, [{"type": "element_visible", "passed": False}]
    )
    await event_service.record_execution_failed(
        execution.id, error_code="VERIFY_FAILED", error_message="Verification failed"
    )

    events = await event_service.get_events(execution.id)
    assert len(events) == 7
    assert events[-1].event_type == EventTypes.EXECUTION_FAILED


@pytest.mark.asyncio
async def test_recovery_lifecycle_events(db_session, execution, event_service):
    """Test recording a recovery scenario."""
    await event_service.record_execution_started(execution.id)
    await event_service.record_browser_started(execution.id)
    await event_service.record_page_loaded(
        execution.id, url="http://example.com", title="Example"
    )
    await event_service.record_action_started(execution.id, "click", "#btn")
    await event_service.record_recovery_started(
        execution.id, reason="Element not found, retrying"
    )
    await event_service.record_action_completed(execution.id, "click", "#btn")
    await event_service.record_execution_completed(execution.id)

    events = await event_service.get_events(execution.id)
    assert len(events) == 7
    assert events[4].event_type == EventTypes.RECOVERY_STARTED
    assert events[4].payload == {"reason": "Element not found, retrying"}


@pytest.mark.asyncio
async def test_events_isolated_per_execution(db_session, flow, event_service):
    """Events from different executions don't mix."""
    repo = ExecutionRepository(db_session)
    exec1 = await repo.create(flow_id=flow.id)
    exec2 = await repo.create(flow_id=flow.id)

    await event_service.record_event(
        exec1.id, EventTypes.EXECUTION_CREATED, {"execution": "1"}
    )
    await event_service.record_event(
        exec2.id, EventTypes.EXECUTION_CREATED, {"execution": "2"}
    )

    events1 = await event_service.get_events(exec1.id)
    events2 = await event_service.get_events(exec2.id)

    assert len(events1) == 1
    assert len(events2) == 1
    assert events1[0].payload == {"execution": "1"}
    assert events2[0].payload == {"execution": "2"}


@pytest.mark.asyncio
async def test_event_types_are_strings():
    """Verify all event types are valid strings."""
    assert isinstance(EventTypes.EXECUTION_CREATED, str)
    assert isinstance(EventTypes.EXECUTION_QUEUED, str)
    assert isinstance(EventTypes.EXECUTION_STARTED, str)
    assert isinstance(EventTypes.BROWSER_STARTED, str)
    assert isinstance(EventTypes.PAGE_LOADED, str)
    assert isinstance(EventTypes.AGENT_OBSERVED, str)
    assert isinstance(EventTypes.ACTION_STARTED, str)
    assert isinstance(EventTypes.ACTION_COMPLETED, str)
    assert isinstance(EventTypes.VERIFICATION_STARTED, str)
    assert isinstance(EventTypes.VERIFICATION_PASSED, str)
    assert isinstance(EventTypes.VERIFICATION_FAILED, str)
    assert isinstance(EventTypes.RECOVERY_STARTED, str)
    assert isinstance(EventTypes.EXECUTION_COMPLETED, str)
    assert isinstance(EventTypes.EXECUTION_FAILED, str)
    assert isinstance(EventTypes.EXECUTION_CANCELLED, str)
