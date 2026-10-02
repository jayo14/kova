import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self, user_id: uuid.UUID, email: str, name: str | None = None
    ) -> User:
        existing = await self.get_by_id(user_id)
        if existing is not None:
            return existing

        user = User(id=user_id, email=email, name=name)
        self.db.add(user)
        await self.db.flush()
        return user
