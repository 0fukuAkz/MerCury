"""Back-compat shim — see :mod:`mercury.services.email` for the implementation.

Existing imports (``from mercury.services.email_service import EmailService``)
and existing test patches
(``patch('mercury.services.email_service.SMTPService')``) continue to resolve
to attributes on this module. New code should import from
``mercury.services.email`` directly.
"""
from .email.config import EmailConfig
from .email.context import SendContext
from .email.service import EmailService

# Preserve the historical module surface so mock.patch targets keep
# resolving. These names are unused by the service itself (it imports
# them directly inside the email package), but legacy tests reference
# them via this module.
from ..engine.async_sender import (  # noqa: F401
    AsyncEmailSender,
    BulkSendResult,
    EmailResult,
)
from .dead_letter_service import DeadLetterService  # noqa: F401
from .smtp_service import SMTPService  # noqa: F401
from .tracking_service import TrackingService  # noqa: F401

__all__ = ['EmailConfig', 'EmailService', 'SendContext']
