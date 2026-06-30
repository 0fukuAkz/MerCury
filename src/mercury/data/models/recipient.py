"""Recipient and recipient list models."""

from enum import Enum
from typing import TYPE_CHECKING, Optional, Any
from sqlalchemy import String, Integer, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, relationship, mapped_column

from ..database import Base
from .base import BaseModel

if TYPE_CHECKING:
    from .campaign import Campaign


class RecipientStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    UNSUBSCRIBED = "unsubscribed"


class RecipientList(Base, BaseModel):
    """Recipient list model."""

    __tablename__ = "recipientlists"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Source
    source_path: Mapped[Optional[str]] = mapped_column(String(500))
    source_type: Mapped[Optional[str]] = mapped_column(
        String(50), default="csv"
    )  # csv, txt, manual

    # Statistics
    total_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    valid_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    invalid_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    suppressed_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    # Settings
    is_validated: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    is_deduplicated: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    # Metadata
    tags: Mapped[Optional[Any]] = mapped_column(JSON, default=list)
    settings: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)

    # Relationships
    recipients: Mapped[list["Recipient"]] = relationship(
        "Recipient", back_populates="recipient_list", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list["Campaign"]] = relationship("Campaign", back_populates="recipient_list")

    def __repr__(self):
        return f"<RecipientList(id={self.id}, name='{self.name}', count={self.total_count})>"


class Recipient(Base, BaseModel):
    """Individual recipient model."""

    __tablename__ = "recipients"

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Parsed email parts
    local_part: Mapped[Optional[str]] = mapped_column(String(255))
    domain: Mapped[Optional[str]] = mapped_column(String(255))
    domain_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Status
    status: Mapped[Optional[str]] = mapped_column(String(50), default=RecipientStatus.PENDING.value)
    is_valid: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    is_suppressed: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    # Custom data from CSV
    first_name: Mapped[Optional[str]] = mapped_column(String(255))
    last_name: Mapped[Optional[str]] = mapped_column(String(255))
    company: Mapped[Optional[str]] = mapped_column(String(255))
    custom_data: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)

    # Validation
    validation_error: Mapped[Optional[str]] = mapped_column(String(500))

    # Relationship
    recipient_list_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recipientlists.id", ondelete="CASCADE")
    )
    recipient_list: Mapped[Optional["RecipientList"]] = relationship(
        "RecipientList", back_populates="recipients"
    )

    @property
    def full_name(self) -> str:
        """Get full name if available."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or (self.local_part or "").capitalize()

    def get_placeholders(self) -> dict:
        """Get all placeholder values for this recipient."""
        placeholders = {
            "email": self.email,
            "local_part": self.local_part,
            "domain": self.domain,
            "domain_name": self.domain_name,
            "first_name": self.first_name or (self.local_part or "").capitalize(),
            "last_name": self.last_name or "",
            "full_name": self.full_name,
            "company": self.company or "",
        }

        if self.custom_data:
            placeholders.update(self.custom_data)

        return placeholders

    def __repr__(self):
        return f"<Recipient(id={self.id}, email='{self.email}')>"
