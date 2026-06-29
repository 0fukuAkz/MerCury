"""Dead letter queue model for permanently failed emails."""

from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON

from .base import Base


class DeadLetter(Base):
    """
    Dead letter queue for permanently failed emails.

    Stores emails that failed permanently (non-transient errors)
    for manual review, analysis, or retry with corrected data.

    NOTE: written in the legacy ``Column(X)`` style (not ``mapped_column``)
    to match the rest of the models and the ``sqlalchemy.ext.mypy.plugin``
    the project relies on — the plugin synthesizes the keyword ``__init__``
    from ``Column`` attributes, which keeps the construction site in
    dead_letter_service type-checked. See CLAUDE.md.
    """

    __tablename__ = "dead_letters"

    id = Column(Integer, primary_key=True)

    # Email details
    recipient = Column(String(255), nullable=False, index=True)
    subject = Column(String(500), nullable=False)
    html_body = Column(Text, nullable=False)
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(255))

    # Campaign reference
    campaign_id = Column(Integer, index=True)
    correlation_id = Column(String(100), index=True)

    # Error details
    error_type = Column(String(100), nullable=False)
    error_message = Column(Text, nullable=False)
    smtp_server = Column(String(100))
    smtp_response = Column(Text)

    # Metadata
    failed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    last_retry_at = Column(DateTime(timezone=True))

    # State
    resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)

    # Additional data
    additional_data = Column(JSON)

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
