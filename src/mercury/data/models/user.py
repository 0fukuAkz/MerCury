"""User model for database-backed authentication."""

from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import BaseModel


class User(Base, BaseModel):
    """
    User model for authentication and authorization.

    This provides database-backed user storage instead of in-memory storage,
    ensuring users persist across application restarts.
    """

    __tablename__ = "users"

    # Core fields
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)

    # Profile
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Permissions
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # API access
    api_key: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    api_key_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Tracking
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)  # Supports IPv6
    login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Password management
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', is_admin={self.is_admin})>"

    def to_dict(self):
        """Convert to dictionary (excludes sensitive fields)."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "must_change_password": self.must_change_password,
        }
