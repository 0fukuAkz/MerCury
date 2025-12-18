"""Repository for dead letter queue."""

from typing import List, Optional
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, and_

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
        self,
        dead_letter_id: int,
        resolution_notes: Optional[str] = None
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
            dead_letter.retry_count += 1
            dead_letter.last_retry_at = datetime.now(UTC)
            return self.update(dead_letter)
        return None
    
    def get_statistics(self) -> dict:
        """
        Get dead letter queue statistics.
        
        Returns:
            Statistics dictionary
        """
        total = self.count()
        unresolved = len(self.get_unresolved(limit=10000))
        
        # Count by error type
        from sqlalchemy import func
        stmt = (
            select(DeadLetter.error_type, func.count(DeadLetter.id))
            .group_by(DeadLetter.error_type)
        )
        error_counts = dict(self.session.execute(stmt).all())
        
        return {
            'total': total,
            'unresolved': unresolved,
            'resolved': total - unresolved,
            'by_error_type': error_counts
        }

