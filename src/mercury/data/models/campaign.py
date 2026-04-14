"""Campaign model with full feature support."""

from enum import Enum
from sqlalchemy import (
    Column, String, Integer, ForeignKey, DateTime, Text, 
    JSON, Enum as SQLEnum, Float, Boolean
)
from sqlalchemy.orm import relationship

from ..database import Base
from .base import BaseModel


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CampaignType(str, Enum):
    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"
    NEWSLETTER = "newsletter"
    PROMOTIONAL = "promotional"
    ANNOUNCEMENT = "announcement"
    OTHER = "other"


class Campaign(Base, BaseModel):
    """Campaign model with full MerCury features."""
    
    __tablename__ = 'campaigns'
    
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    type = Column(SQLEnum(CampaignType), default=CampaignType.MARKETING, nullable=False)
    status = Column(SQLEnum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False, index=True)
    
    # Relationships
    template_id = Column(Integer, ForeignKey('templates.id', ondelete='SET NULL'))
    recipient_list_id = Column(Integer, ForeignKey('recipientlists.id', ondelete='SET NULL'))
    
    template = relationship("Template", back_populates="campaigns")
    recipient_list = relationship("RecipientList", back_populates="campaigns")
    email_logs = relationship("EmailLog", back_populates="campaign", cascade="all, delete-orphan")
    smtp_configs = relationship("CampaignSMTPConfig", back_populates="campaign", cascade="all, delete-orphan")
    
    # Scheduling
    scheduled_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Statistics
    total_recipients = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    queued_count = Column(Integer, default=0)
    
    # Settings stored as JSON
    settings = Column(JSON, default=dict)
    
    # Subject configuration (supports rotation)
    subjects = Column(JSON, default=list)
    subject_rotation_strategy = Column(String(50), default='round_robin')
    
    # FROM configuration
    from_email = Column(String(255))
    from_name = Column(String(255))
    reply_to = Column(String(255))
    
    # Placeholders
    placeholders = Column(JSON, default=dict)
    
    # Content conversion settings
    convert_to_image = Column(Boolean, default=False)
    convert_to_pdf = Column(Boolean, default=False)
    enable_qr_code = Column(Boolean, default=False)
    
    # Bulk sending configuration
    chunk_size = Column(Integer, default=10000)
    concurrency = Column(Integer, default=100)
    pause_between_chunks = Column(Integer, default=30)
    rate_per_minute = Column(Integer, default=0)
    rate_per_hour = Column(Integer, default=0)
    
    # SMTP rotation
    smtp_rotation_strategy = Column(String(50), default='weighted')
    auto_failover = Column(Boolean, default=True)
    
    # Organization
    tags = Column(JSON, default=list)
    last_used_at = Column(DateTime)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        if self.sent_count == 0:
            return 0.0
        return round((self.delivered_count / self.sent_count) * 100, 2)
    
    @property
    def is_editable(self) -> bool:
        """Check if campaign can be edited."""
        return self.status in [CampaignStatus.DRAFT, CampaignStatus.SCHEDULED]
    
    @property
    def is_active(self) -> bool:
        """Check if campaign is currently active."""
        return self.status == CampaignStatus.SENDING
    
    def __repr__(self):
        return f"<Campaign(id={self.id}, name='{self.name}', status={self.status.value})>"


class CampaignSMTPConfig(Base, BaseModel):
    """Junction table for campaign-SMTP many-to-many relationship."""
    
    __tablename__ = 'campaign_smtp_configs'
    
    campaign_id = Column(Integer, ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False)
    smtp_server_id = Column(Integer, ForeignKey('smtpservers.id', ondelete='CASCADE'), nullable=False)
    
    weight = Column(Float, default=1.0)
    priority = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    
    campaign = relationship("Campaign", back_populates="smtp_configs")
    smtp_server = relationship("SMTPServer", back_populates="campaign_configs")

