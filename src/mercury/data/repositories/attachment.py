"""Attachment repository."""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..models import Attachment


class AttachmentRepository(BaseRepository[Attachment]):
    """Repository for Attachment entities."""

    def __init__(self, session: Session):
        super().__init__(session, Attachment)

    def list_active(self) -> List[Attachment]:
        stmt = (
            select(Attachment)
            .where(Attachment.is_active.is_(True))
            .order_by(Attachment.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_by_stored_name(self, stored_name: str) -> Optional[Attachment]:
        stmt = select(Attachment).where(Attachment.stored_name == stored_name)
        return self.session.execute(stmt).scalar_one_or_none()
