"""Bounce handling service for managing email bounces and suppressions."""

import os
import logging
from typing import Optional, Dict, Any, List, Set
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
    Service for handling email bounces and maintaining suppression lists.
    
    Features:
    - Categorize bounces (hard/soft)
    - Maintain suppression list
    - Track soft bounce counts
    - Export suppression list
    """
    
    # Soft bounce threshold - after this many soft bounces, treat as hard
    SOFT_BOUNCE_THRESHOLD = 3
    
    def __init__(self, suppression_file: Optional[str] = None):
        """
        Initialize bounce service.
        
        Args:
            suppression_file: Path to suppression list file
        """
        self.suppression_file = suppression_file or os.environ.get(
            'SUPPRESSION_FILE',
            'data/suppression_list.txt'
        )
        
        self._suppression_list: Set[str] = set()
        self._soft_bounce_counts: Dict[str, int] = {}
        self._bounces: List[BounceRecord] = []
        
        # Load existing suppression list
        self._load_suppression_list()
    
    def _load_suppression_list(self) -> None:
        """Load suppression list from file."""
        if not os.path.exists(self.suppression_file):
            return
        
        try:
            with open(self.suppression_file, 'r', encoding='utf-8') as f:
                for line in f:
                    email = line.strip().lower()
                    if email and not email.startswith('#'):
                        self._suppression_list.add(email)
            
            logger.info(f"Loaded {len(self._suppression_list)} suppressed emails")
            
        except Exception as e:
            logger.error(f"Failed to load suppression list: {e}")
    
    def _save_suppression_list(self) -> None:
        """Save suppression list to file."""
        try:
            os.makedirs(os.path.dirname(self.suppression_file) or '.', exist_ok=True)
            
            with open(self.suppression_file, 'w', encoding='utf-8') as f:
                f.write(f"# Suppression list - Updated {datetime.now(UTC).isoformat()}\n")
                for email in sorted(self._suppression_list):
                    f.write(f"{email}\n")
            
            logger.debug(f"Saved {len(self._suppression_list)} suppressed emails")
            
        except Exception as e:
            logger.error(f"Failed to save suppression list: {e}")
    
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
        
        # Handle based on bounce type
        if bounce_type == BounceType.HARD:
            self.add_to_suppression_list(email)
            logger.info(f"Hard bounce: {email} - Added to suppression list")
        
        elif bounce_type == BounceType.SOFT:
            count = self._soft_bounce_counts.get(email, 0) + 1
            self._soft_bounce_counts[email] = count
            
            if count >= self.SOFT_BOUNCE_THRESHOLD:
                self.add_to_suppression_list(email)
                logger.info(f"Soft bounce threshold reached: {email} - Added to suppression list")
            else:
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
        self.add_to_suppression_list(email)
        
        logger.warning(f"Spam complaint: {email} - Added to suppression list")
        
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
        self.add_to_suppression_list(email)
        
        logger.info(f"Unsubscribe: {email} - Added to suppression list")
        
        return record
    
    def add_to_suppression_list(self, email: str) -> None:
        """Add email to suppression list."""
        email = email.lower().strip()
        if email not in self._suppression_list:
            self._suppression_list.add(email)
            self._save_suppression_list()
    
    def remove_from_suppression_list(self, email: str) -> bool:
        """Remove email from suppression list."""
        email = email.lower().strip()
        if email in self._suppression_list:
            self._suppression_list.discard(email)
            self._save_suppression_list()
            return True
        return False
    
    def is_suppressed(self, email: str) -> bool:
        """Check if email is on suppression list."""
        return email.lower().strip() in self._suppression_list
    
    def filter_recipients(self, emails: List[str]) -> tuple[List[str], List[str]]:
        """
        Filter recipient list against suppression list.
        
        Args:
            emails: List of email addresses
            
        Returns:
            Tuple of (allowed_emails, suppressed_emails)
        """
        allowed = []
        suppressed = []
        
        for email in emails:
            if self.is_suppressed(email):
                suppressed.append(email)
            else:
                allowed.append(email)
        
        if suppressed:
            logger.info(f"Filtered {len(suppressed)} suppressed emails from {len(emails)} recipients")
        
        return allowed, suppressed
    
    def get_suppression_list(self) -> List[str]:
        """Get current suppression list."""
        return sorted(self._suppression_list)
    
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
            'suppression_list_size': len(self._suppression_list),
            'by_category': {
                category.value: len([b for b in self._bounces if b.category == category])
                for category in BounceCategory
            }
        }
    
    def export_suppression_list(self, filepath: str) -> int:
        """
        Export suppression list to file.
        
        Args:
            filepath: Output file path
            
        Returns:
            Number of emails exported
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Suppression list export - {datetime.now(UTC).isoformat()}\n")
            for email in sorted(self._suppression_list):
                f.write(f"{email}\n")
        
        return len(self._suppression_list)
    
    def import_suppression_list(self, filepath: str) -> int:
        """
        Import emails to suppression list.
        
        Args:
            filepath: Input file path
            
        Returns:
            Number of emails imported
        """
        count = 0
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                email = line.strip().lower()
                if email and not email.startswith('#') and '@' in email:
                    if email not in self._suppression_list:
                        self._suppression_list.add(email)
                        count += 1
        
        self._save_suppression_list()
        logger.info(f"Imported {count} emails to suppression list")
        
        return count

