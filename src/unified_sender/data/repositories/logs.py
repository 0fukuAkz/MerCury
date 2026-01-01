
from typing import List, Optional, Dict, Any
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
