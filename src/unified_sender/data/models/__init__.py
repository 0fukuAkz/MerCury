"""SQLAlchemy models for unified sender."""

from .base import BaseModel
from .campaign import Campaign, CampaignStatus, CampaignType
from .smtp import SMTPServer, SMTPServerStatus
from .template import Template
from .recipient import RecipientList, Recipient, RecipientStatus
from .email_log import EmailLog, EmailStatus
from .user import User

__all__ = [
    "BaseModel",
    "Campaign",
    "CampaignStatus",
    "CampaignType",
    "SMTPServer",
    "SMTPServerStatus",
    "Template",
    "RecipientList",
    "Recipient",
    "RecipientStatus",
    "EmailLog",
    "EmailStatus",
    "User",
]

