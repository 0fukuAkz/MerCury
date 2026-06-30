"""Email log model for tracking sent emails."""

from enum import Enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Any
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, relationship, mapped_column

from ..database import Base
from .base import BaseModel

if TYPE_CHECKING:
    from .campaign import Campaign


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

    __tablename__ = "emaillogs"

    # Identifiers
    campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)

    # Recipient
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Email content snapshot
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    from_email: Mapped[Optional[str]] = mapped_column(String(255))
    from_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Status
    status: Mapped[Optional[str]] = mapped_column(
        String(50), default=EmailStatus.PENDING.value, index=True
    )

    # SMTP info
    smtp_server_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("smtpservers.id", ondelete="SET NULL")
    )
    smtp_server_name: Mapped[Optional[str]] = mapped_column(String(100))
    smtp_response: Mapped[Optional[str]] = mapped_column(Text)

    # Timing
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    clicked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Error handling
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_type: Mapped[Optional[str]] = mapped_column(String(50))
    retry_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    max_retries: Mapped[Optional[int]] = mapped_column(Integer, default=3)

    # Tracking
    open_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    click_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    # Last-observed engagement metadata (most recent open or click).
    # Populated by the tracking endpoints (web/routes/tracking.py); read by
    # the campaign send path to backfill {{location.*}} / {{ua.*}}
    # placeholders for recipients whose CSV row doesn't include them.
    last_event_ip: Mapped[Optional[str]] = mapped_column(String(45))  # IPv6 max length = 45
    last_event_ua: Mapped[Optional[str]] = mapped_column(String(500))
    last_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Extra data (renamed from 'metadata' which is reserved in SQLAlchemy)
    extra_data: Mapped[Optional[Any]] = mapped_column("metadata", JSON, default=dict)

    # Relationships
    campaign: Mapped[Optional["Campaign"]] = relationship("Campaign", back_populates="email_logs")

    @property
    def is_successful(self) -> bool:
        """Check if email was sent successfully."""
        return self.status in [
            EmailStatus.SENT.value,
            EmailStatus.DELIVERED.value,
            EmailStatus.OPENED.value,
            EmailStatus.CLICKED.value,
        ]

    @property
    def is_retriable(self) -> bool:
        """Check if email can be retried."""
        retried = self.retry_count or 0
        max_retries = self.max_retries or 0
        return (
            self.status in [EmailStatus.FAILED.value, EmailStatus.RETRYING.value]
            and retried < max_retries
        )

    def __repr__(self):
        return f"<EmailLog(id={self.id}, recipient='{self.recipient_email}', status={self.status})>"
