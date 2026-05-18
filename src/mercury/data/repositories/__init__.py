"""Repository pattern for data access."""

from .base import BaseRepository
from .campaign import CampaignRepository
from .smtp import SMTPRepository
from .template import TemplateRepository
from .recipient import RecipientRepository, RecipientListRepository
from .user import UserRepository
from .logs import LogRepository
from .attachment import AttachmentRepository

__all__ = [
    "BaseRepository",
    "CampaignRepository",
    "SMTPRepository",
    "TemplateRepository",
    "RecipientRepository",
    "RecipientListRepository",
    "UserRepository",
    "LogRepository",
    "AttachmentRepository",
]

