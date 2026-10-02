import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.exploration.models import (
    ExplorationEvent,
    ExplorationSession,
    ExplorationStatus,
)


class ExplorationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID,
        url: str,
        goal: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> ExplorationSession:
        session = ExplorationSession(
            user_id=user_id,
            url=url,
            goal=goal,
            project_id=project_id,
            status=ExplorationStatus.CREATED.value,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_by_id(self, session_id: uuid.UUID) -> ExplorationSession | None:
        result = await self.db.execute(
            select(ExplorationSession).where(ExplorationSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> ExplorationSession | None:
        result = await self.db.execute(
            select(ExplorationSession).where(
                ExplorationSession.id == session_id,
                ExplorationSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: uuid.UUID, skip: int = 0, limit: int = 50
    ) -> list[ExplorationSession]:
        result = await self.db.execute(
            select(ExplorationSession)
            .where(ExplorationSession.user_id == user_id)
            .order_by(ExplorationSession.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        session_id: uuid.UUID,
        status: ExplorationStatus | str | None = None,
        error_message: str | None = None,
        discoveries: list[dict] | None = None,
        candidate_missions: list[dict] | None = None,
        question: dict | None = None,
        credential_request: dict | None = None,
        selected_role: str | None = None,
        project_id: uuid.UUID | None = None,
    ) -> ExplorationSession | None:
        session = await self.get_by_id(session_id)
        if session is None:
            return None

        if status is not None:
            status_val = status.value if isinstance(status, ExplorationStatus) else status
            session.status = status_val
        if error_message is not None:
            session.error_message = error_message
        if discoveries is not None:
            session.discoveries = discoveries
        if candidate_missions is not None:
            session.candidate_missions = candidate_missions
        if question is not None:
            session.question = question
        if credential_request is not None:
            session.credential_request = credential_request
        if selected_role is not None:
            session.selected_role = selected_role
        if project_id is not None:
            session.project_id = project_id

        session.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session


class ExplorationEventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        exploration_id: uuid.UUID,
        event_type: str,
        payload: dict | None = None,
    ) -> ExplorationEvent:
        event = ExplorationEvent(
            exploration_id=exploration_id,
            event_type=event_type,
            payload=payload or {},
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def list_by_session(
        self,
        exploration_id: uuid.UUID,
        skip: int = 0,
        limit: int = 1000,
        after_id: uuid.UUID | None = None,
    ) -> list[ExplorationEvent]:
        query = (
            select(ExplorationEvent)
            .where(ExplorationEvent.exploration_id == exploration_id)
            .order_by(ExplorationEvent.created_at.asc())
        )
        if after_id:
            sub = select(ExplorationEvent.created_at).where(ExplorationEvent.id == after_id).scalar_subquery()
            query = query.where(ExplorationEvent.created_at > sub)

        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())
