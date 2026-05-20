"""Email service package — composing and sending emails with all features.

The orchestration lives in ``service.EmailService``; the build-time helpers
(branding, extras, attachment materialization, obfuscation) sit alongside
as small, single-purpose modules so each step of ``send_single`` is
independently testable.
"""
from .config import EmailConfig
from .context import SendContext
from .service import EmailService

__all__ = ['EmailConfig', 'EmailService', 'SendContext']
