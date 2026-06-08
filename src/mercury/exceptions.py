"""Custom exceptions for MerCury."""

from typing import Optional, Dict, Any


class MercuryException(Exception):
    """Base exception for all MerCury errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize exception.

        Args:
            message: Error message
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


# Configuration Errors


class ConfigurationException(MercuryException):
    """Error in configuration (YAML, settings, etc.)."""

    pass


class InvalidConfigValueError(ConfigurationException):
    """Invalid configuration value."""

    pass


class MissingConfigError(ConfigurationException):
    """Required configuration is missing."""

    pass


# Validation Errors


class ValidationException(MercuryException):
    """Input validation failed."""

    pass


class InvalidEmailError(ValidationException):
    """Email address is invalid."""

    pass


class InvalidRecipientError(ValidationException):
    """Recipient data is invalid or malformed."""

    pass


class InvalidTemplateError(ValidationException):
    """Template syntax or content is invalid."""

    pass


# SMTP Errors


class SMTPException(MercuryException):
    """Base SMTP error."""

    def __init__(
        self,
        message: str,
        smtp_server: Optional[str] = None,
        smtp_response: Optional[str] = None,
        is_transient: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize SMTP exception.

        Args:
            message: Error message
            smtp_server: SMTP server name/host
            smtp_response: Response from SMTP server
            is_transient: Whether error is transient (retriable)
            details: Additional details
        """
        details = details or {}
        if smtp_server:
            details["smtp_server"] = smtp_server
        if smtp_response:
            details["smtp_response"] = smtp_response
        details["is_transient"] = is_transient

        super().__init__(message, details)
        self.smtp_server = smtp_server
        self.smtp_response = smtp_response
        self.is_transient = is_transient


class TransientSMTPError(SMTPException):
    """Transient SMTP error (can be retried)."""

    def __init__(self, message: str, **kwargs):
        kwargs["is_transient"] = True
        super().__init__(message, **kwargs)


class PermanentSMTPError(SMTPException):
    """Permanent SMTP error (should not retry)."""

    def __init__(self, message: str, **kwargs):
        kwargs["is_transient"] = False
        super().__init__(message, **kwargs)


class SMTPConnectionError(TransientSMTPError):
    """Failed to connect to SMTP server."""

    pass


class SMTPAuthenticationError(PermanentSMTPError):
    """SMTP authentication failed."""

    pass


class SMTPRateLimitError(TransientSMTPError):
    """SMTP rate limit exceeded."""

    pass


class SMTPMailboxError(PermanentSMTPError):
    """Mailbox does not exist or is invalid."""

    pass


# Database Errors


class DatabaseException(MercuryException):
    """Database operation failed."""

    pass


class RecordNotFoundError(DatabaseException):
    """Database record not found."""

    pass


class DuplicateRecordError(DatabaseException):
    """Duplicate record detected."""

    pass


# Campaign Errors


class CampaignException(MercuryException):
    """Campaign-related error."""

    pass


class CampaignNotFoundError(CampaignException):
    """Campaign not found."""

    pass


class CampaignAlreadyRunningError(CampaignException):
    """Campaign is already running."""

    pass


class CampaignInvalidStateError(CampaignException):
    """Campaign in invalid state for operation."""

    pass


# Template Errors


class TemplateException(MercuryException):
    """Template rendering error."""

    pass


class TemplateNotFoundError(TemplateException):
    """Template file not found."""

    pass


class TemplateSyntaxError(TemplateException):
    """Template has syntax errors."""

    pass


class PlaceholderError(TemplateException):
    """Placeholder-related error."""

    pass


# Feature Errors


class FeatureException(MercuryException):
    """Feature-specific error."""

    pass


class QRCodeGenerationError(FeatureException):
    """Failed to generate QR code."""

    pass


class AttachmentError(FeatureException):
    """Attachment generation/handling failed."""

    pass


class TrackingError(FeatureException):
    """Tracking service error."""

    pass


# Rate Limiting Errors


class RateLimitException(MercuryException):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str,
        retry_after: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize rate limit exception.

        Args:
            message: Error message
            retry_after: Seconds until rate limit resets
            details: Additional details
        """
        details = details or {}
        if retry_after is not None:
            details["retry_after"] = retry_after

        super().__init__(message, details)
        self.retry_after = retry_after


# Security Errors


class SecurityException(MercuryException):
    """Security-related error."""

    pass


class AuthenticationError(SecurityException):
    """Authentication failed."""

    pass


class AuthorizationError(SecurityException):
    """Authorization/permission denied."""

    pass


class EncryptionError(SecurityException):
    """Encryption/decryption failed."""

    pass


# Webhook Errors


class WebhookException(MercuryException):
    """Webhook-related error."""

    pass


class WebhookDeliveryError(WebhookException):
    """Failed to deliver webhook."""

    pass


class WebhookValidationError(WebhookException):
    """Webhook payload validation failed."""

    pass


# Utility Functions


def is_transient_error(error: Exception) -> bool:
    """
    Check if error is transient (retriable).

    Args:
        error: Exception to check

    Returns:
        True if error is transient
    """
    if isinstance(error, TransientSMTPError):
        return True
    if isinstance(error, SMTPException):
        return error.is_transient
    if isinstance(error, RateLimitException):
        return True
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True

    return False


def categorize_exception(error: Exception) -> str:
    """
    Categorize exception for logging/monitoring.

    Args:
        error: Exception to categorize

    Returns:
        Category string
    """
    if isinstance(error, SMTPException):
        return "smtp_error"
    elif isinstance(error, DatabaseException):
        return "database_error"
    elif isinstance(error, ValidationException):
        return "validation_error"
    elif isinstance(error, ConfigurationException):
        return "configuration_error"
    elif isinstance(error, SecurityException):
        return "security_error"
    elif isinstance(error, RateLimitException):
        return "rate_limit_error"
    else:
        return "unknown_error"
