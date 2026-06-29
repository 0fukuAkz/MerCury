"""Repository for dead letter queue."""

from typing import List, Optional
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, update

from .base import BaseRepository
from ..models.dead_letter import DeadLetter


class DeadLetterRepository(BaseRepository[DeadLetter]):
    """Repository for dead letter queue operations."""

    def __init__(self, session):
        super().__init__(session, DeadLetter)

    def get_by_recipient(self, recipient: str) -> List[DeadLetter]:
        """
        Get all dead letters for a recipient.

        Args:
            recipient: Email address

        Returns:
            List of dead letters
        """
        stmt = select(DeadLetter).where(DeadLetter.recipient == recipient)
        return list(self.session.execute(stmt).scalars())

    def get_by_campaign(self, campaign_id: int) -> List[DeadLetter]:
        """
        Get all dead letters for a campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            List of dead letters
        """
        stmt = select(DeadLetter).where(DeadLetter.campaign_id == campaign_id)
        return list(self.session.execute(stmt).scalars())

    def get_unresolved(self, limit: int = 100) -> List[DeadLetter]:
        """
        Get unresolved dead letters.

        Args:
            limit: Maximum number to return

        Returns:
            List of unresolved dead letters
        """
        stmt = (
            select(DeadLetter)
            .where(DeadLetter.resolved == False)
            .order_by(DeadLetter.failed_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def get_by_error_type(self, error_type: str, limit: int = 100) -> List[DeadLetter]:
        """
        Get dead letters by error type.

        Args:
            error_type: Error type to filter by
            limit: Maximum number to return

        Returns:
            List of matching dead letters
        """
        stmt = (
            select(DeadLetter)
            .where(DeadLetter.error_type == error_type)
            .order_by(DeadLetter.failed_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def get_recent(self, hours: int = 24, limit: int = 100) -> List[DeadLetter]:
        """
        Get recent dead letters.

        Args:
            hours: Number of hours to look back
            limit: Maximum number to return

        Returns:
            List of recent dead letters
        """
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        stmt = (
            select(DeadLetter)
            .where(DeadLetter.failed_at >= cutoff)
            .order_by(DeadLetter.failed_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def mark_resolved(
        self, dead_letter_id: int, resolution_notes: Optional[str] = None
    ) -> Optional[DeadLetter]:
        """
        Mark dead letter as resolved.

        Args:
            dead_letter_id: Dead letter ID
            resolution_notes: Optional resolution notes

        Returns:
            Updated dead letter or None
        """
        dead_letter = self.get(dead_letter_id)
        if dead_letter:
            dead_letter.resolved = True
            dead_letter.resolved_at = datetime.now(UTC)
            dead_letter.resolution_notes = resolution_notes
            return self.update(dead_letter)
        return None

    def mark_all_unresolved_as_resolved(self, resolution_notes: Optional[str] = None) -> int:
        """Bulk-resolve every unresolved row in one statement.

        Returns the number of rows affected. Implemented as a single SQL
        UPDATE rather than a per-row loop because the alternative — load
        each DeadLetter, set attributes, commit — fsyncs once per row on
        SQLite and turns a 10k-row "Discard All" into a 30s blocking
        operation. The bulk form completes in milliseconds.

        Like ``mark_resolved``, this does NOT delete rows — the payload
        is preserved so operators can investigate discarded items later.
        Rows simply disappear from ``get_unresolved`` results.
        """
        now = datetime.now(UTC)
        stmt = (
            update(DeadLetter)
            .where(DeadLetter.resolved.is_(False))
            .values(
                resolved=True,
                resolved_at=now,
                resolution_notes=resolution_notes,
            )
        )
        result = self.session.execute(stmt)
        # ``session_scope`` does not commit on normal exit; the other write
        # methods on BaseRepository each commit themselves, so this bulk
        # path must do the same or the UPDATE is rolled back at close time
        # (which is exactly how the "discard all reports success but nothing
        # is deleted" bug manifested).
        self.session.commit()
        # rowcount lives on CursorResult; the Result base type mypy infers
        # doesn't expose it, so reach for it defensively.
        return int(getattr(result, "rowcount", 0) or 0)

    def increment_retry_count(self, dead_letter_id: int) -> Optional[DeadLetter]:
        """
        Increment retry count for dead letter.

        Args:
            dead_letter_id: Dead letter ID

        Returns:
            Updated dead letter or None
        """
        dead_letter = self.get(dead_letter_id)
        if dead_letter:
            dead_letter.retry_count = (dead_letter.retry_count or 0) + 1
            dead_letter.last_retry_at = datetime.now(UTC)
            return self.update(dead_letter)
        return None

    def get_statistics(self) -> dict:
        """
        Get dead letter queue statistics.

        Returns:
            Statistics dictionary
        """
        from sqlalchemy import func

        total = self.count()

        unresolved_stmt = select(func.count(DeadLetter.id)).where(DeadLetter.resolved == False)
        unresolved = self.session.execute(unresolved_stmt).scalar() or 0

        retried_stmt = select(func.count(DeadLetter.id)).where(DeadLetter.retry_count > 0)
        retried = self.session.execute(retried_stmt).scalar() or 0

        discarded_stmt = select(func.count(DeadLetter.id)).where(DeadLetter.resolved == True)
        discarded = self.session.execute(discarded_stmt).scalar() or 0

        # Count by error type
        stmt = select(DeadLetter.error_type, func.count(DeadLetter.id)).group_by(
            DeadLetter.error_type
        )
        error_counts: dict[str, int] = {
            etype: count for etype, count in self.session.execute(stmt).all()
        }

        return {
            "total": total,
            "unresolved": unresolved,
            "resolved": discarded,
            "by_error_type": error_counts,
            # Keys mapped exactly for the UI
            "pending": unresolved,
            "total_processed": total,
            "retried": retried,
            "discarded": discarded,
        }
