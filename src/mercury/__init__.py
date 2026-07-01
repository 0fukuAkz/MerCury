"""
MerCury Email Platform - Production-grade email automation platform.

Features:
- High-performance async sending (100-300 emails/second)
- Connection pooling with circuit breaker
- Multi-SMTP load balancing
- Rate limiting with token bucket algorithm
- Retry queue with exponential backoff
- 50+ template placeholders
- QR code, PDF, DOCX generation
- Email tracking (opens, clicks)
- Bounce handling and suppression lists
- Webhook notifications
- Scheduled sending
- Web UI with authentication
- API with rate limiting
"""

__version__ = "2.1.0"
__author__ = "MerCury Team"

from .services import (
    CampaignService,
    EmailService,
    SMTPService,
    TrackingService,
    BounceService,
    WebhookService,
    SchedulerService,
)

# Export main exceptions for convenience
from .exceptions import (
    MercuryException,
    ConfigurationException,
    ValidationException,
    SMTPException,
    TransientSMTPError,
    PermanentSMTPError,
    DatabaseException,
    RateLimitException,
)

__all__ = [
    "__version__",
    "CampaignService",
    "EmailService",
    "SMTPService",
    "TrackingService",
    "BounceService",
    "WebhookService",
    "SchedulerService",
    "MercuryException",
    "ConfigurationException",
    "ValidationException",
    "SMTPException",
    "TransientSMTPError",
    "PermanentSMTPError",
    "DatabaseException",
    "RateLimitException",
]
