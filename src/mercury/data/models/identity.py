"""Sender Identity models (From Emails and Sender Names)."""

from typing import Optional, Any
from sqlalchemy import String, Boolean, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base
from .base import BaseModel


class FromEmail(Base, BaseModel):
    """Pool of 'From' email addresses."""

    __tablename__ = "from_emails"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    tags: Mapped[Optional[Any]] = mapped_column(
        JSON, default=list
    )  # e.g., ["marketing", "newsletter"]

    # Tracking stats
    use_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[str]] = mapped_column(String(50))  # ISO format date

    def __repr__(self):
        return f"<FromEmail(email='{self.email}')>"


class SenderName(Base, BaseModel):
    """Pool of 'From' sender names."""

    __tablename__ = "sender_names"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    tags: Mapped[Optional[Any]] = mapped_column(JSON, default=list)

    # Tracking stats
    use_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[str]] = mapped_column(String(50))

    def __repr__(self):
        return f"<SenderName(name='{self.name}')>"
