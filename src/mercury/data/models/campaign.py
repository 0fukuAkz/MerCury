"""Campaign model with full feature support."""

from enum import Enum
from sqlalchemy import (
    Column,
    String,
    Integer,
    ForeignKey,
    DateTime,
    Text,
    JSON,
    Enum as SQLEnum,
    Float,
    Boolean,
)
from sqlalchemy.orm import relationship, validates

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

    __tablename__ = "campaigns"

    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    type = Column(SQLEnum(CampaignType), default=CampaignType.MARKETING, nullable=False)
    status = Column(
        SQLEnum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False, index=True
    )

    # Relationships
    template_id = Column(Integer, ForeignKey("templates.id", ondelete="SET NULL"))
    recipient_list_id = Column(Integer, ForeignKey("recipientlists.id", ondelete="SET NULL"))

    template = relationship("Template", back_populates="campaigns")
    recipient_list = relationship("RecipientList", back_populates="campaigns")
    email_logs = relationship("EmailLog", back_populates="campaign", cascade="all, delete-orphan")
    smtp_configs = relationship(
        "CampaignSMTPConfig", back_populates="campaign", cascade="all, delete-orphan"
    )

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
    subject_rotation_strategy = Column(String(50), default="round_robin")

    # FROM configuration
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
    smtp_rotation_strategy = Column(String(50), default="weighted")
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
    def send_rate(self) -> float:
        """Sent / total_recipients as percentage."""
        if not self.total_recipients:
            return 0.0
        return round(self.sent_count / self.total_recipients * 100, 1)

    def to_dict(self) -> dict:
        result = super().to_dict()
        # computed fields not stored as columns
        result["send_rate"] = self.send_rate
        try:
            result["template_name"] = self.template.name if self.template else None
        except Exception:
            result["template_name"] = None
        s = self.settings or {}
        result["dry_run"] = bool(s.get("dry_run", False))
        # surface settings-stored fields at top level so the form/UI can read them directly
        result["recipients_path"] = s.get("recipients_path", "")
        result["manual_recipients_count"] = len(s.get("manual_recipients", []) or [])
        result["subject"] = (self.subjects[0] if self.subjects else "") or ""
        result["from_emails"] = s.get("from_emails") or []
        result["from_names"] = s.get("from_names") or []
        result["links"] = s.get("links") or []
        result["template_path"] = s.get("template_path", "")
        result["templates"] = s.get("templates") or []
        # Pinned SMTP server (None / absent = use all enabled servers)
        _smtp_id = s.get("smtp_server_id")
        result["smtp_server_id"] = int(_smtp_id) if _smtp_id is not None else None
        # Attachments library bindings (legacy attachment_path/type removed)
        result["attachment_ids"] = list(s.get("attachment_ids") or [])
        result["convert_attachment"] = bool(s.get("convert_attachment", False))
        result["attachment_convert_to"] = s.get("attachment_convert_to") or ""
        _logo_id = s.get("logo_attachment_id")
        result["logo_attachment_id"] = int(_logo_id) if _logo_id is not None else None
        result["auto_company_logo"] = bool(s.get("auto_company_logo", False))
        result["hide_from_email_header"] = bool(s.get("hide_from_email_header", False))
        result["include_default_body"] = bool(s.get("include_default_body", True))

        # Tracking settings
        result["enable_tracking"] = bool(s.get("enable_tracking", True))
        result["track_opens"] = bool(s.get("track_opens", True))
        result["track_clicks"] = bool(s.get("track_clicks", True))
        result["tracking_base_url"] = s.get("tracking_base_url", "")

        # Recipient-list options. Defaults TRUE on both (sane production
        # default) — explicit False is only stored when the operator
        # toggled the box off.
        result["validate_emails"] = bool(s.get("validate_emails", True))
        result["deduplicate"] = bool(s.get("deduplicate", True))
        result["mail_priority"] = s.get("mail_priority", "3")
        if self.started_at and self.completed_at:
            result["duration_seconds"] = int((self.completed_at - self.started_at).total_seconds())
        else:
            result["duration_seconds"] = None
        return result

    @property
    def is_editable(self) -> bool:
        """Check if campaign can be edited."""
        return self.status in [CampaignStatus.DRAFT, CampaignStatus.SCHEDULED]

    @property
    def is_active(self) -> bool:
        """Check if campaign is currently active."""
        return self.status == CampaignStatus.SENDING

    @property
    def from_emails(self):
        return (self.settings or {}).get("from_emails") or []

    @from_emails.setter
    def from_emails(self, value):
        if self.settings is None:
            self.settings = {}
        # Ensure we work with a copy or dict update to trigger SQLAlchemy tracked mutations
        s = dict(self.settings)
        s["from_emails"] = list(value) if value is not None else []
        self.settings = s

    @property
    def from_names(self):
        return (self.settings or {}).get("from_names") or []

    @from_names.setter
    def from_names(self, value):
        if self.settings is None:
            self.settings = {}
        s = dict(self.settings)
        s["from_names"] = list(value) if value is not None else []
        self.settings = s

    @property
    def from_email(self) -> str:
        emails = self.from_emails
        return emails[0] if emails else ""

    @from_email.setter
    def from_email(self, value: str):
        self.from_emails = [value] if value else []

    @property
    def from_name(self) -> str:
        names = self.from_names
        return names[0] if names else ""

    @from_name.setter
    def from_name(self, value: str):
        self.from_names = [value] if value else []

    @validates('settings')
    def validate_settings(self, key, value):
        if value is None:
            value = {}
        else:
            value = dict(value)
        if self.settings:
            for k in ["from_emails", "from_names"]:
                if k in self.settings and k not in value:
                    value[k] = self.settings[k]
        return value

    def __repr__(self):
        return f"<Campaign(id={self.id}, name='{self.name}', status={self.status.value})>"


class CampaignSMTPConfig(Base, BaseModel):
    """Junction table for campaign-SMTP many-to-many relationship."""

    __tablename__ = "campaign_smtp_configs"

    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    smtp_server_id = Column(
        Integer, ForeignKey("smtpservers.id", ondelete="CASCADE"), nullable=False
    )

    weight = Column(Float, default=1.0)
    priority = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)

    campaign = relationship("Campaign", back_populates="smtp_configs")
    smtp_server = relationship("SMTPServer", back_populates="campaign_configs")
