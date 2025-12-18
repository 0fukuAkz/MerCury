"""Recipient and recipient list models."""

from enum import Enum
from sqlalchemy import Column, String, Integer, ForeignKey, Text, Boolean, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from .base import BaseModel


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
    
    __tablename__ = 'recipientlists'
    
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    
    # Source
    source_path = Column(String(500))
    source_type = Column(String(50), default='csv')  # csv, txt, manual
    
    # Statistics
    total_count = Column(Integer, default=0)
    valid_count = Column(Integer, default=0)
    invalid_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    suppressed_count = Column(Integer, default=0)
    
    # Settings
    is_validated = Column(Boolean, default=False)
    is_deduplicated = Column(Boolean, default=False)
    
    # Metadata
    tags = Column(JSON, default=list)
    settings = Column(JSON, default=dict)
    
    # Relationships
    recipients = relationship("Recipient", back_populates="recipient_list", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="recipient_list")
    
    def __repr__(self):
        return f"<RecipientList(id={self.id}, name='{self.name}', count={self.total_count})>"


class Recipient(Base, BaseModel):
    """Individual recipient model."""
    
    __tablename__ = 'recipients'
    
    email = Column(String(255), nullable=False, index=True)
    
    # Parsed email parts
    local_part = Column(String(255))
    domain = Column(String(255))
    domain_name = Column(String(255))
    
    # Status
    status = Column(String(50), default=RecipientStatus.PENDING.value)
    is_valid = Column(Boolean, default=True)
    is_suppressed = Column(Boolean, default=False)
    
    # Custom data from CSV
    first_name = Column(String(255))
    last_name = Column(String(255))
    company = Column(String(255))
    custom_data = Column(JSON, default=dict)
    
    # Validation
    validation_error = Column(String(500))
    
    # Relationship
    recipient_list_id = Column(Integer, ForeignKey('recipientlists.id', ondelete='CASCADE'))
    recipient_list = relationship("RecipientList", back_populates="recipients")
    
    @property
    def full_name(self) -> str:
        """Get full name if available."""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or self.local_part.capitalize()
    
    def get_placeholders(self) -> dict:
        """Get all placeholder values for this recipient."""
        placeholders = {
            'email': self.email,
            'local_part': self.local_part,
            'domain': self.domain,
            'domain_name': self.domain_name,
            'first_name': self.first_name or self.local_part.capitalize(),
            'last_name': self.last_name or '',
            'full_name': self.full_name,
            'company': self.company or '',
        }
        
        if self.custom_data:
            placeholders.update(self.custom_data)
        
        return placeholders
    
    def __repr__(self):
        return f"<Recipient(id={self.id}, email='{self.email}')>"

