"""Recipient repository."""

from typing import Optional, List, Iterator
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from .base import BaseRepository
from ..models import RecipientList, Recipient, RecipientStatus


class RecipientListRepository(BaseRepository[RecipientList]):
    """Repository for RecipientList entities."""

    def __init__(self, session: Session):
        super().__init__(session, RecipientList)

    def get_by_name(self, name: str) -> Optional[RecipientList]:
        """Get recipient list by name."""
        stmt = select(RecipientList).where(RecipientList.name == name)
        return self.session.execute(stmt).scalar_one_or_none()


class RecipientRepository(BaseRepository[Recipient]):
    """Repository for Recipient entities."""

    def __init__(self, session: Session):
        super().__init__(session, Recipient)

    def get_by_email(self, email: str) -> Optional[Recipient]:
        """Get recipient by email."""
        stmt = select(Recipient).where(Recipient.email == email)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_list(self, list_id: int, limit: int = 1000, offset: int = 0) -> List[Recipient]:
        """Get recipients by list ID."""
        stmt = (
            select(Recipient)
            .where(Recipient.recipient_list_id == list_id)
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.execute(stmt).scalars())

    def get_pending_by_list(self, list_id: int, limit: int = 1000) -> List[Recipient]:
        """Get pending recipients for a list."""
        stmt = (
            select(Recipient)
            .where(
                Recipient.recipient_list_id == list_id,
                Recipient.status == RecipientStatus.PENDING.value,
                Recipient.is_valid == True,
                Recipient.is_suppressed == False,
            )
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def iterate_by_list(
        self, list_id: int, batch_size: int = 1000, pending_only: bool = True
    ) -> Iterator[List[Recipient]]:
        """Iterate through recipients in batches."""
        offset = 0
        while True:
            if pending_only:
                batch = self.get_pending_by_list(list_id, limit=batch_size)
            else:
                batch = self.get_by_list(list_id, limit=batch_size, offset=offset)

            if not batch:
                break

            yield batch

            if not pending_only:
                offset += batch_size
            else:
                # For pending, we mark as queued so next query gets new batch
                break

    def update_status(self, recipient_id: int, status: RecipientStatus) -> Optional[Recipient]:
        """Update recipient status."""
        recipient = self.get(recipient_id)
        if recipient:
            recipient.status = status.value
            self.session.commit()
        return recipient

    def bulk_update_status(self, recipient_ids: List[int], status: RecipientStatus):
        """Bulk update recipient status."""
        stmt = select(Recipient).where(Recipient.id.in_(recipient_ids))
        for recipient in self.session.execute(stmt).scalars():
            recipient.status = status.value
        self.session.commit()

    def count_by_status(self, list_id: int) -> dict:
        """Get count by status for a list."""
        stmt = (
            select(Recipient.status, func.count(Recipient.id))
            .where(Recipient.recipient_list_id == list_id)
            .group_by(Recipient.status)
        )
        results = self.session.execute(stmt).all()
        return {status: count for status, count in results}

    def get_valid_count(self, list_id: int) -> int:
        """Get count of valid recipients."""
        stmt = select(func.count(Recipient.id)).where(
            Recipient.recipient_list_id == list_id, Recipient.is_valid == True
        )
        return self.session.execute(stmt).scalar() or 0

    def suppress_email(self, email: str) -> bool:
        """Suppress an email address."""
        stmt = select(Recipient).where(Recipient.email == email)
        for recipient in self.session.execute(stmt).scalars():
            recipient.is_suppressed = True
            recipient.status = RecipientStatus.SUPPRESSED.value
        self.session.commit()
        return True

    def bulk_create(self, recipients: List[Recipient]) -> int:
        """Bulk create recipients."""
        self.session.add_all(recipients)
        self.session.commit()
        return len(recipients)
