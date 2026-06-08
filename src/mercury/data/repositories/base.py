"""Base repository with common CRUD operations."""

from typing import TypeVar, Generic, Optional, List, Type
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, session: Session, model: Type[T]):
        self.session = session
        self.model = model

    def get(self, id: int) -> Optional[T]:
        """Get entity by ID."""
        return self.session.get(self.model, id)

    def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Get all entities with pagination."""
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars())

    def create(self, entity: T) -> T:
        """Create new entity."""
        self.session.add(entity)
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def bulk_create(self, entities: List[T]) -> int:
        """Insert many entities in a single transaction.

        Skips per-row ``refresh()`` for throughput; auto-generated primary
        keys are still populated by SQLAlchemy after flush. Returns the
        number of rows added.
        """
        if not entities:
            return 0
        self.session.add_all(entities)
        self.session.commit()
        return len(entities)

    def update(self, entity: T) -> T:
        """Update existing entity."""
        self.session.commit()
        self.session.refresh(entity)
        return entity

    def delete(self, entity: T) -> bool:
        """Delete entity."""
        self.session.delete(entity)
        self.session.commit()
        return True

    def delete_by_id(self, id: int) -> bool:
        """Delete entity by ID."""
        entity = self.get(id)
        if entity:
            return self.delete(entity)
        return False

    def count(self) -> int:
        """Count total entities."""
        from sqlalchemy import func

        stmt = select(func.count()).select_from(self.model)
        result = self.session.execute(stmt).scalar()
        return result or 0

    def exists(self, id: int) -> bool:
        """Check if entity exists."""
        return self.get(id) is not None
