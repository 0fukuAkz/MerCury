
from typing import List, Dict, Optional, Tuple
from sqlalchemy import func, desc, select
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..models import EmailLog, EmailStatus

class LogRepository(BaseRepository[EmailLog]):
    """Repository for managing email logs."""

    def __init__(self, session: Session):
        super().__init__(session, EmailLog)

    def get_by_campaign(self, campaign_id: int, limit: int = 100, offset: int = 0) -> List[EmailLog]:
        """Get logs for a specific campaign."""
        stmt = select(EmailLog).where(
            EmailLog.campaign_id == campaign_id
        ).order_by(
            desc(EmailLog.created_at)
        ).limit(limit).offset(offset)
        
        return list(self.session.scalars(stmt).all())

    def get_recent_success(self, limit: int = 100) -> List[EmailLog]:
        """Get recent successful email logs."""
        stmt = select(EmailLog).where(
            EmailLog.status.in_([
                EmailStatus.SENT.value,
                EmailStatus.DELIVERED.value,
                EmailStatus.OPENED.value,
                EmailStatus.CLICKED.value
            ])
        ).order_by(
            desc(EmailLog.sent_at)
        ).limit(limit)
        
        return list(self.session.scalars(stmt).all())

    def get_recent_failed(self, limit: int = 100) -> List[EmailLog]:
        """Get recent failed email logs."""
        stmt = select(EmailLog).where(
            EmailLog.status.in_([
                EmailStatus.FAILED.value, 
                EmailStatus.BOUNCED.value
            ])
        ).order_by(
            desc(EmailLog.failed_at)
        ).limit(limit)
        
        return list(self.session.scalars(stmt).all())

    def get_last_event_for_recipient(self, email: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (ip, user_agent) from the most-recent open/click for ``email``.

        Used by the campaign send path to backfill geo + UA placeholders
        for recipients whose CSV row doesn't include them. ``(None, None)``
        means "no engagement on file" — caller should fall back to empty
        placeholder values, not raise.

        Searches across ALL campaigns by recipient_email (not scoped to one
        campaign) — a recipient who opened campaign A last week is the same
        person you're sending campaign B to today.
        """
        stmt = select(
            EmailLog.last_event_ip,
            EmailLog.last_event_ua,
        ).where(
            EmailLog.recipient_email == email,
            EmailLog.last_event_at.is_not(None),
        ).order_by(
            desc(EmailLog.last_event_at)
        ).limit(1)
        row = self.session.execute(stmt).first()
        if row is None:
            return (None, None)
        return (row[0], row[1])

    def get_last_events_bulk(self, emails: List[str]) -> Dict[str, Tuple[str, str]]:
        """Bulk variant of get_last_event_for_recipient.

        Returns ``{email: (ip, ua)}`` for every email that has any engagement
        on file. Emails with no events are simply absent from the result —
        the caller can iterate the input list and treat missing keys as
        "no enrichment available".

        Implemented as one query rather than N: a window function would be
        ideal but isn't portable across SQLite/PostgreSQL old enough to be
        in the wild. Two-pass groupby is good enough for the recipient
        sizes we see (10k-100k per campaign) and avoids the N+1 trap.
        """
        if not emails:
            return {}

        # Most recent timestamp per recipient
        sub = select(
            EmailLog.recipient_email,
            func.max(EmailLog.last_event_at).label('max_ts'),
        ).where(
            EmailLog.recipient_email.in_(emails),
            EmailLog.last_event_at.is_not(None),
        ).group_by(EmailLog.recipient_email).subquery()

        # Join back to grab the IP/UA at that timestamp
        stmt = select(
            EmailLog.recipient_email,
            EmailLog.last_event_ip,
            EmailLog.last_event_ua,
        ).join(
            sub,
            (EmailLog.recipient_email == sub.c.recipient_email)
            & (EmailLog.last_event_at == sub.c.max_ts),
        )
        out: Dict[str, Tuple[str, str]] = {}
        for email, ip, ua in self.session.execute(stmt).all():
            # Guard against duplicate timestamps (rare; pick first seen).
            out.setdefault(email, (ip or '', ua or ''))
        return out

    def get_global_stats(self) -> Dict[str, int]:
        """Get global sending statistics efficiently."""
        
        # We use a single query to group by status and count
        stmt = select(
            EmailLog.status, 
            func.count(EmailLog.id)
        ).group_by(EmailLog.status)
        
        results = self.session.execute(stmt).all()
        status_counts = {r[0]: r[1] for r in results}
        
        total_sent = sum(status_counts.get(s.value, 0) for s in [
            EmailStatus.SENT, EmailStatus.DELIVERED, 
            EmailStatus.OPENED, EmailStatus.CLICKED
        ])
        
        total_failed = sum(status_counts.get(s.value, 0) for s in [
            EmailStatus.FAILED, EmailStatus.BOUNCED
        ])
        
        # Pending/queued/retrying are considered "in progress" or just total attempts
        total_attempts = sum(status_counts.values())
        
        return {
            'total_sent': total_sent,
            'total_failed': total_failed,
            'total_attempts': total_attempts,
            'success_rate': round(total_sent / total_attempts * 100, 2) if total_attempts > 0 else 0
        }
