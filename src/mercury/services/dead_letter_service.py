"""Service for managing dead letter queue."""

from typing import Optional, Dict, Any, List
from datetime import datetime, UTC

from ..data.repositories.dead_letter import DeadLetterRepository
from ..data.models.dead_letter import DeadLetter
from ..utils.logging_context import get_context_logger

logger = get_context_logger(__name__)


class DeadLetterService:
    """Service for dead letter queue operations."""
    
    def __init__(self, repository: DeadLetterRepository):
        """
        Initialize dead letter service.
        
        Args:
            repository: Dead letter repository
        """
        self.repository = repository
    
    def add_dead_letter(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        from_email: str,
        error_type: str,
        error_message: str,
        from_name: Optional[str] = None,
        campaign_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
        smtp_server: Optional[str] = None,
        smtp_response: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ) -> DeadLetter:
        """
        Add email to dead letter queue.
        
        Args:
            recipient: Email recipient
            subject: Email subject
            html_body: Email HTML content
            from_email: Sender email
            error_type: Type of error
            error_message: Error message
            from_name: Sender name
            campaign_id: Campaign ID if applicable
            correlation_id: Correlation tracking ID
            smtp_server: SMTP server that failed
            smtp_response: SMTP server response
            additional_data: Additional metadata
            
        Returns:
            Created dead letter entry
        """
        dead_letter = DeadLetter(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=from_email,
            from_name=from_name,
            campaign_id=campaign_id,
            correlation_id=correlation_id,
            error_type=error_type,
            error_message=error_message,
            smtp_server=smtp_server,
            smtp_response=smtp_response,
            failed_at=datetime.now(UTC),
            retry_count=0,
            resolved=False,
            additional_data=additional_data
        )
        
        created = self.repository.create(dead_letter)
        
        logger.warning(
            "💀 Added to dead letter queue",
            recipient=recipient,
            error_type=error_type,
            dead_letter_id=created.id
        )
        
        return created
    
    def get_unresolved(self, limit: int = 100) -> List[DeadLetter]:
        """Get unresolved dead letters."""
        return self.repository.get_unresolved(limit=limit)
    
    def get_by_campaign(self, campaign_id: int) -> List[DeadLetter]:
        """Get dead letters for a campaign."""
        return self.repository.get_by_campaign(campaign_id)
    
    def get_by_error_type(self, error_type: str) -> List[DeadLetter]:
        """Get dead letters by error type."""
        return self.repository.get_by_error_type(error_type)
    
    def mark_resolved(
        self,
        dead_letter_id: int,
        resolution_notes: Optional[str] = None
    ) -> Optional[DeadLetter]:
        """
        Mark dead letter as resolved.
        
        Args:
            dead_letter_id: ID of dead letter
            resolution_notes: Notes about resolution
            
        Returns:
            Updated dead letter or None
        """
        updated = self.repository.mark_resolved(dead_letter_id, resolution_notes)
        
        if updated:
            logger.info(
                "✅ Dead letter marked resolved",
                dead_letter_id=dead_letter_id,
                recipient=updated.recipient
            )
        
        return updated
    
    def discard_all_unresolved(self, resolution_notes: Optional[str] = None) -> int:
        """Mark every unresolved row as resolved in one bulk UPDATE.

        Returns the number of rows affected. Used by the "Discard All"
        action in the dead-letter UI. See repository docstring for why
        this is a single SQL statement rather than a Python loop.
        """
        count = self.repository.mark_all_unresolved_as_resolved(resolution_notes)
        if count > 0:
            logger.info("🧹 Bulk-discarded dead letters", count=count)
        return count

    def retry_dead_letter(self, dead_letter_id: int) -> Optional[DeadLetter]:
        """
        Increment retry counter for dead letter.
        
        Args:
            dead_letter_id: Dead letter ID
            
        Returns:
            Updated dead letter
        """
        return self.repository.increment_retry_count(dead_letter_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get dead letter queue statistics.
        
        Returns:
            Statistics dictionary
        """
        return self.repository.get_statistics()
    
    def cleanup_resolved(self, days_old: int = 30) -> int:
        """
        Clean up old resolved dead letters.
        
        Args:
            days_old: Delete resolved letters older than this
            
        Returns:
            Number of deleted records
        """
        from datetime import timedelta
        from sqlalchemy import select, and_
        
        cutoff = datetime.now(UTC) - timedelta(days=days_old)
        
        stmt = select(DeadLetter).where(
            and_(
                DeadLetter.resolved == True,
                DeadLetter.resolved_at < cutoff
            )
        )
        
        old_letters = list(self.repository.session.execute(stmt).scalars())
        
        for letter in old_letters:
            self.repository.delete(letter)
        
        logger.info(f"🧹 Cleaned up {len(old_letters)} old resolved dead letters")
        
        return len(old_letters)

