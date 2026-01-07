"""Sender Identity models (From Emails and Sender Names)."""

from sqlalchemy import Column, String, Boolean, JSON, Integer
from ..database import Base
from .base import BaseModel

class FromEmail(Base, BaseModel):
    """Pool of 'From' email addresses."""
    
    __tablename__ = 'from_emails'
    
    email = Column(String(255), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    tags = Column(JSON, default=list)  # e.g., ["marketing", "newsletter"]
    
    # Tracking stats
    use_count = Column(Integer, default=0)
    last_used_at = Column(String(50))  # ISO format date

    def __repr__(self):
        return f"<FromEmail(email='{self.email}')>"

class SenderName(Base, BaseModel):
    """Pool of 'From' sender names."""
    
    __tablename__ = 'sender_names'
    
    name = Column(String(255), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    tags = Column(JSON, default=list)
    
    # Tracking stats
    use_count = Column(Integer, default=0)
    last_used_at = Column(String(50))

    def __repr__(self):
        return f"<SenderName(name='{self.name}')>"
