"""Dead letter queue model for permanently failed emails."""

from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import Integer, String, Text, DateTime, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DeadLetter(Base):
    """
    Dead letter queue for permanently failed emails.

    Stores emails that failed permanently (non-transient errors)
    for manual review, analysis, or retry with corrected data.
    """

    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Email details
    recipient: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Campaign reference
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)

    # Error details
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    smtp_server: Mapped[Optional[str]] = mapped_column(String(100))
    smtp_response: Mapped[Optional[str]] = mapped_column(Text)

    # Metadata
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # State
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)

    # Additional data
    additional_data: Mapped[Optional[dict]] = mapped_column(JSON)

    def __repr__(self) -> str:
        return (
            f"<DeadLetter(id={self.id}, recipient='{self.recipient}', "
            f"error='{self.error_type}', resolved={self.resolved})>"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "recipient": self.recipient,
            "subject": self.subject,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "campaign_id": self.campaign_id,
            "correlation_id": self.correlation_id,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "smtp_server": self.smtp_server,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
            "retry_count": self.retry_count,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }
