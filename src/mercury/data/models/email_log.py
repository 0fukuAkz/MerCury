"""Email log model for tracking sent emails."""

from enum import Enum
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from .base import BaseModel


class EmailStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"
    RETRYING = "retrying"


class EmailLog(Base, BaseModel):
    """Email sending log model."""
    
    __tablename__ = 'emaillogs'
    
    # Identifiers
    campaign_id = Column(Integer, ForeignKey('campaigns.id', ondelete='CASCADE'), index=True)
    correlation_id = Column(String(100), unique=True, index=True)
    
    # Recipient
    recipient_email = Column(String(255), nullable=False, index=True)

    # Email content snapshot
    subject = Column(String(500))
    from_email = Column(String(255))
    from_name = Column(String(255))
    
    # Status
    status = Column(String(50), default=EmailStatus.PENDING.value, index=True)
    
    # SMTP info
    smtp_server_id = Column(Integer, ForeignKey('smtpservers.id', ondelete='SET NULL'))
    smtp_server_name = Column(String(100))
    smtp_response = Column(Text)
    
    # Timing
    queued_at = Column(DateTime)
    sent_at = Column(DateTime)
    delivered_at = Column(DateTime)
    opened_at = Column(DateTime)
    clicked_at = Column(DateTime)
    failed_at = Column(DateTime)
    
    # Error handling
    error_message = Column(Text)
    error_type = Column(String(50))
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # Tracking
    open_count = Column(Integer, default=0)
    click_count = Column(Integer, default=0)

    # Last-observed engagement metadata (most recent open or click).
    # Populated by the tracking endpoints (web/routes/tracking.py); read by
    # the campaign send path to backfill {{location.*}} / {{ua.*}}
    # placeholders for recipients whose CSV row doesn't include them.
    last_event_ip = Column(String(45))   # IPv6 max length = 45
    last_event_ua = Column(String(500))
    last_event_at = Column(DateTime)
    
    # Extra data (renamed from 'metadata' which is reserved in SQLAlchemy)
    extra_data = Column('metadata', JSON, default=dict)
    
    # Relationships
    campaign = relationship("Campaign", back_populates="email_logs")
    
    @property
    def is_successful(self) -> bool:
        """Check if email was sent successfully."""
        return self.status in [
            EmailStatus.SENT.value, 
            EmailStatus.DELIVERED.value,
            EmailStatus.OPENED.value,
            EmailStatus.CLICKED.value
        ]
    
    @property
    def is_retriable(self) -> bool:
        """Check if email can be retried."""
        return (
            self.status in [EmailStatus.FAILED.value, EmailStatus.RETRYING.value] and
            self.retry_count < self.max_retries
        )
    
    def __repr__(self):
        return f"<EmailLog(id={self.id}, recipient='{self.recipient_email}', status={self.status})>"

