import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.repository import ExecutionEventRepository, ExecutionRepository
from app.modules.executions.event_types import EventTypes


class EventService:
    """Service for recording and querying execution events.

    Events are the first-class primitive for tracking execution history.
    Every significant state change is recorded as an event with a timestamp.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.event_repo = ExecutionEventRepository(db)
        self.exec_repo = ExecutionRepository(db)

    async def record_event(
        self,
        execution_id: uuid.UUID,
        event_type: str,
        payload: dict | None = None,
    ):
        """Record an event for an execution.

        Args:
            execution_id: The execution to record the event for.
            event_type: One of the EventTypes constants.
            payload: Optional data payload for the event.

        Returns:
            The created ExecutionEvent record.
        """
        return await self.event_repo.create(
            execution_id=execution_id,
            event_type=event_type,
            payload=payload or {},
        )

    async def get_events(
        self,
        execution_id: uuid.UUID,
        skip: int = 0,
        limit: int = 1000,
    ):
        """Get chronological event history for an execution.

        Events are returned in ascending order by created_at (oldest first).
        """
        return await self.event_repo.list_by_execution(
            execution_id, skip=skip, limit=limit
        )

    async def get_event_count(self, execution_id: uuid.UUID) -> int:
        """Get total number of events for an execution."""
        events = await self.event_repo.list_by_execution(
            execution_id, skip=0, limit=1
        )
        # Use the repo's list which returns all, but we just need count
        all_events = await self.event_repo.list_by_execution(execution_id)
        return len(all_events)

    async def record_execution_created(self, execution_id: uuid.UUID):
        """Record that an execution was created."""
        return await self.record_event(
            execution_id, EventTypes.EXECUTION_CREATED, {"status": "created"}
        )

    async def record_execution_queued(self, execution_id: uuid.UUID):
        """Record that an execution was queued."""
        return await self.record_event(
            execution_id, EventTypes.EXECUTION_QUEUED, {"status": "queued"}
        )

    async def record_execution_started(self, execution_id: uuid.UUID):
        """Record that an execution started running."""
        return await self.record_event(
            execution_id, EventTypes.EXECUTION_STARTED, {"status": "started"}
        )

    async def record_browser_started(self, execution_id: uuid.UUID):
        """Record that the browser was launched."""
        return await self.record_event(
            execution_id, EventTypes.BROWSER_STARTED, {"browser": "chromium"}
        )

    async def record_page_loaded(
        self, execution_id: uuid.UUID, url: str, title: str
    ):
        """Record that a page finished loading."""
        return await self.record_event(
            execution_id,
            EventTypes.PAGE_LOADED,
            {"url": url, "title": title},
        )

    async def record_agent_observed(
        self, execution_id: uuid.UUID, observation: dict
    ):
        """Record an agent observation of the page."""
        return await self.record_event(
            execution_id, EventTypes.AGENT_OBSERVED, observation
        )

    async def record_action_started(
        self, execution_id: uuid.UUID, action: str, target: str
    ):
        """Record that an action was started."""
        return await self.record_event(
            execution_id,
            EventTypes.ACTION_STARTED,
            {"action": action, "target": target},
        )

    async def record_action_completed(
        self, execution_id: uuid.UUID, action: str, target: str
    ):
        """Record that an action completed successfully."""
        return await self.record_event(
            execution_id,
            EventTypes.ACTION_COMPLETED,
            {"action": action, "target": target},
        )

    async def record_verification_started(self, execution_id: uuid.UUID):
        """Record that verification was started."""
        return await self.record_event(
            execution_id, EventTypes.VERIFICATION_STARTED, {}
        )

    async def record_verification_passed(
        self, execution_id: uuid.UUID, checks: list[dict]
    ):
        """Record that verification passed."""
        return await self.record_event(
            execution_id,
            EventTypes.VERIFICATION_PASSED,
            {"checks": checks},
        )

    async def record_verification_failed(
        self, execution_id: uuid.UUID, checks: list[dict]
    ):
        """Record that verification failed."""
        return await self.record_event(
            execution_id,
            EventTypes.VERIFICATION_FAILED,
            {"checks": checks},
        )

    async def record_recovery_started(
        self, execution_id: uuid.UUID, reason: str
    ):
        """Record that recovery was started."""
        return await self.record_event(
            execution_id,
            EventTypes.RECOVERY_STARTED,
            {"reason": reason},
        )

    async def record_execution_completed(
        self, execution_id: uuid.UUID, result: dict | None = None
    ):
        """Record that an execution completed successfully."""
        return await self.record_event(
            execution_id,
            EventTypes.EXECUTION_COMPLETED,
            {"result": result} if result else {},
        )

    async def record_execution_failed(
        self, execution_id: uuid.UUID, error_code: str, error_message: str
    ):
        """Record that an execution failed."""
        return await self.record_event(
            execution_id,
            EventTypes.EXECUTION_FAILED,
            {"error_code": error_code, "error_message": error_message},
        )

    async def record_execution_cancelled(self, execution_id: uuid.UUID):
        """Record that an execution was cancelled."""
        return await self.record_event(
            execution_id, EventTypes.EXECUTION_CANCELLED, {"status": "cancelled"}
        )
