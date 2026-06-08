"""User model for database-backed authentication."""

from sqlalchemy import Column, String, Boolean, DateTime, Integer

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
    username = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(512), nullable=False)

    # Profile
    display_name = Column(String(255), nullable=True)

    # Permissions
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # API access
    api_key = Column(String(64), unique=True, nullable=True, index=True)
    api_key_created_at = Column(DateTime, nullable=True)

    # Tracking
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)  # Supports IPv6
    login_count = Column(Integer, default=0, nullable=False)

    # Password management
    password_changed_at = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, default=False, nullable=False)

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
