"""CustomPlaceholder repository."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..models import CustomPlaceholder


class CustomPlaceholderRepository(BaseRepository[CustomPlaceholder]):
    """Repository for CustomPlaceholder entities."""

    def __init__(self, session: Session):
        super().__init__(session, CustomPlaceholder)

    def list_all(self) -> List[CustomPlaceholder]:
        """All rows, active or not — used by the admin page."""
        stmt = select(CustomPlaceholder).order_by(CustomPlaceholder.name.asc())
        return list(self.session.execute(stmt).scalars())

    def list_active(self) -> List[CustomPlaceholder]:
        """Active rows only — used by the engine when configuring a send."""
        stmt = (
            select(CustomPlaceholder)
            .where(CustomPlaceholder.is_active.is_(True))
            .order_by(CustomPlaceholder.name.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_by_name(self, name: str) -> Optional[CustomPlaceholder]:
        stmt = select(CustomPlaceholder).where(CustomPlaceholder.name == name)
        return self.session.execute(stmt).scalar_one_or_none()
