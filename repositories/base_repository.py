from typing import TypeVar, Generic, Type, List, Optional, Union
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from core.database import Base

ModelType = TypeVar("ModelType", bound=Base)

class BaseRepository(Generic[ModelType]):
    """Async repository pattern with safe session handling."""

    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, session: AsyncSession, id: UUID) -> Optional[ModelType]:
        return await session.get(self.model, id)

    async def get_all(self, session: AsyncSession, skip: int = 0, limit: int = 100) -> List[ModelType]:
        result = await session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def create(self, session: AsyncSession, obj_in: dict) -> ModelType:
        db_obj = self.model(**obj_in)
        session.add(db_obj)
        await session.commit()
        await session.refresh(db_obj)
        return db_obj

    async def update(self, session: AsyncSession, id: UUID, update_data: dict) -> Optional[ModelType]:
        obj = await self.get(session, id)
        if not obj:
            return None
        for key, value in update_data.items():
            setattr(obj, key, value)
        await session.commit()
        await session.refresh(obj)
        return obj

    async def delete(self, session: AsyncSession, id: UUID) -> bool:
        obj = await self.get(session, id)
        if not obj:
            return False
        await session.delete(obj)
        await session.commit()
        return True