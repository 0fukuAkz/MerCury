"""Bounce handling service for managing email bounces and suppressions."""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class BounceType(str, Enum):
    """Type of email bounce."""
    HARD = "hard"  # Permanent failure (invalid address)
    SOFT = "soft"  # Temporary failure (mailbox full, server down)
    COMPLAINT = "complaint"  # User marked as spam
    UNSUBSCRIBE = "unsubscribe"  # User unsubscribed


class BounceCategory(str, Enum):
    """Category of bounce for reporting."""
    INVALID_ADDRESS = "invalid_address"
    MAILBOX_FULL = "mailbox_full"
    BLOCKED = "blocked"
    SPAM = "spam"
    TECHNICAL = "technical"
    POLICY = "policy"
    UNKNOWN = "unknown"


@dataclass
class BounceRecord:
    """Record of an email bounce."""
    id: str
    email: str
    bounce_type: BounceType
    category: BounceCategory
    timestamp: datetime
    reason: str = ""
    smtp_code: Optional[str] = None
    campaign_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'email': self.email,
            'bounce_type': self.bounce_type.value,
            'category': self.category.value,
            'timestamp': self.timestamp.isoformat(),
            'reason': self.reason,
            'smtp_code': self.smtp_code,
            'campaign_id': self.campaign_id,
            'metadata': self.metadata
        }


class BounceService:
    """
    Service for handling email bounces.
    
    Features:
    - Categorize bounces (hard/soft)
    - Track soft bounce counts
    """
    
    # Soft bounce threshold - after this many soft bounces, treat as hard
    SOFT_BOUNCE_THRESHOLD = 3
    
    def __init__(self, suppression_file: Optional[str] = None):
        """
        Initialize bounce service.
        """
        self._soft_bounce_counts: Dict[str, int] = {}
        self._bounces: List[BounceRecord] = []
    
    def categorize_bounce(
        self,
        smtp_code: Optional[str],
        error_message: str
    ) -> tuple[BounceType, BounceCategory]:
        """
        Categorize a bounce based on SMTP code and error message.
        
        Args:
            smtp_code: SMTP error code (e.g., "550")
            error_message: Error message from server
            
        Returns:
            Tuple of (BounceType, BounceCategory)
        """
        error_lower = error_message.lower()
        
        # Hard bounces (5xx errors)
        hard_bounce_patterns = [
            ('does not exist', BounceCategory.INVALID_ADDRESS),
            ('no such user', BounceCategory.INVALID_ADDRESS),
            ('unknown user', BounceCategory.INVALID_ADDRESS),
            ('invalid recipient', BounceCategory.INVALID_ADDRESS),
            ('mailbox not found', BounceCategory.INVALID_ADDRESS),
            ('user unknown', BounceCategory.INVALID_ADDRESS),
            ('blocked', BounceCategory.BLOCKED),
            ('blacklist', BounceCategory.BLOCKED),
            ('spam', BounceCategory.SPAM),
            ('rejected', BounceCategory.POLICY),
            ('policy', BounceCategory.POLICY),
        ]
        
        for pattern, category in hard_bounce_patterns:
            if pattern in error_lower:
                return BounceType.HARD, category
        
        # Soft bounces (4xx errors)
        soft_bounce_patterns = [
            ('mailbox full', BounceCategory.MAILBOX_FULL),
            ('quota', BounceCategory.MAILBOX_FULL),
            ('temporarily', BounceCategory.TECHNICAL),
            ('try again', BounceCategory.TECHNICAL),
            ('busy', BounceCategory.TECHNICAL),
            ('timeout', BounceCategory.TECHNICAL),
            ('rate limit', BounceCategory.POLICY),
            ('too many', BounceCategory.POLICY),
        ]
        
        for pattern, category in soft_bounce_patterns:
            if pattern in error_lower:
                return BounceType.SOFT, category
        
        # Check SMTP code
        if smtp_code:
            if smtp_code.startswith('5'):
                if smtp_code in ['550', '551', '552', '553', '554']:
                    return BounceType.HARD, BounceCategory.INVALID_ADDRESS
            elif smtp_code.startswith('4'):
                return BounceType.SOFT, BounceCategory.TECHNICAL
        
        # Default to soft bounce for unknown errors
        return BounceType.SOFT, BounceCategory.UNKNOWN
    
    def process_bounce(
        self,
        email: str,
        error_message: str,
        smtp_code: Optional[str] = None,
        campaign_id: Optional[str] = None
    ) -> BounceRecord:
        """
        Process a bounce notification.
        
        Args:
            email: Bounced email address
            error_message: Error message from SMTP server
            smtp_code: SMTP error code
            campaign_id: Campaign ID if applicable
            
        Returns:
            BounceRecord with categorization
        """
        import uuid
        
        email = email.lower().strip()
        bounce_type, category = self.categorize_bounce(smtp_code, error_message)
        
        record = BounceRecord(
            id=str(uuid.uuid4()),
            email=email,
            bounce_type=bounce_type,
            category=category,
            timestamp=datetime.now(UTC),
            reason=error_message,
            smtp_code=smtp_code,
            campaign_id=campaign_id
        )
        
        self._bounces.append(record)
        
        # Track soft bounce counts
        if bounce_type == BounceType.HARD:
            logger.info(f"Hard bounce: {email}")
        elif bounce_type == BounceType.SOFT:
            count = self._soft_bounce_counts.get(email, 0) + 1
            self._soft_bounce_counts[email] = count
            logger.debug(f"Soft bounce {count}/{self.SOFT_BOUNCE_THRESHOLD}: {email}")
        
        return record
    
    def process_complaint(
        self,
        email: str,
        campaign_id: Optional[str] = None
    ) -> BounceRecord:
        """
        Process a spam complaint.
        
        Args:
            email: Complainer email address
            campaign_id: Campaign ID if applicable
            
        Returns:
            BounceRecord for the complaint
        """
        import uuid
        
        email = email.lower().strip()
        
        record = BounceRecord(
            id=str(uuid.uuid4()),
            email=email,
            bounce_type=BounceType.COMPLAINT,
            category=BounceCategory.SPAM,
            timestamp=datetime.now(UTC),
            reason="Spam complaint received",
            campaign_id=campaign_id
        )
        
        self._bounces.append(record)
        
        logger.warning(f"Spam complaint: {email}")
        
        return record
    
    def process_unsubscribe(
        self,
        email: str,
        campaign_id: Optional[str] = None
    ) -> BounceRecord:
        """
        Process an unsubscribe request.
        
        Args:
            email: Unsubscriber email address
            campaign_id: Campaign ID if applicable
            
        Returns:
            BounceRecord for the unsubscribe
        """
        import uuid
        
        email = email.lower().strip()
        
        record = BounceRecord(
            id=str(uuid.uuid4()),
            email=email,
            bounce_type=BounceType.UNSUBSCRIBE,
            category=BounceCategory.POLICY,
            timestamp=datetime.now(UTC),
            reason="User unsubscribed",
            campaign_id=campaign_id
        )
        
        self._bounces.append(record)
        
        logger.info(f"Unsubscribe: {email}")
        
        return record
    
    def get_bounce_stats(self) -> Dict[str, Any]:
        """Get bounce statistics."""
        hard_bounces = [b for b in self._bounces if b.bounce_type == BounceType.HARD]
        soft_bounces = [b for b in self._bounces if b.bounce_type == BounceType.SOFT]
        complaints = [b for b in self._bounces if b.bounce_type == BounceType.COMPLAINT]
        unsubscribes = [b for b in self._bounces if b.bounce_type == BounceType.UNSUBSCRIBE]
        
        return {
            'total_bounces': len(self._bounces),
            'hard_bounces': len(hard_bounces),
            'soft_bounces': len(soft_bounces),
            'complaints': len(complaints),
            'unsubscribes': len(unsubscribes),
            'suppression_list_size': 0,
            'by_category': {
                category.value: len([b for b in self._bounces if b.category == category])
                for category in BounceCategory
            }
        }
    


