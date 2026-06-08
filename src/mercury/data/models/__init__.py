"""SQLAlchemy models for MerCury."""

from .base import BaseModel
from .campaign import Campaign, CampaignStatus, CampaignType
from .smtp import SMTPServer, SMTPServerStatus
from .template import Template
from .recipient import RecipientList, Recipient, RecipientStatus
from .email_log import EmailLog, EmailStatus
from .user import User
from .identity import FromEmail, SenderName
from .settings import GlobalSetting
from .dead_letter import DeadLetter
from .attachment import Attachment
from .placeholder import CustomPlaceholder

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
    "FromEmail",
    "SenderName",
    "GlobalSetting",
    "DeadLetter",
    "Attachment",
    "CustomPlaceholder",
]
