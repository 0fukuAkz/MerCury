"""Email validation utilities using email-validator library."""

import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass
from email_validator import validate_email as _validate_email, EmailNotValidError

from ..exceptions import InvalidEmailError, ValidationException

logger = logging.getLogger(__name__)


@dataclass
class EmailValidationResult:
    """Result of email validation."""
    email: str
    is_valid: bool
    normalized_email: Optional[str] = None
    local_part: Optional[str] = None
    domain: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            'email': self.email,
            'is_valid': self.is_valid,
            'normalized_email': self.normalized_email,
            'local_part': self.local_part,
            'domain': self.domain,
            'error': self.error
        }


def validate_email(
    email: str,
    check_deliverability: bool = False,
    allow_smtputf8: bool = True
) -> EmailValidationResult:
    """
    Validate an email address using the email-validator library.
    
    Args:
        email: Email address to validate
        check_deliverability: If True, check DNS MX records (slower)
        allow_smtputf8: Allow internationalized email addresses
        
    Returns:
        EmailValidationResult with validation details
    """
    email = email.strip() if email else ""
    
    if not email:
        return EmailValidationResult(
            email=email,
            is_valid=False,
            error="Empty email address"
        )
    
    try:
        result = _validate_email(
            email,
            check_deliverability=check_deliverability,
            allow_smtputf8=allow_smtputf8
        )
        
        return EmailValidationResult(
            email=email,
            is_valid=True,
            normalized_email=result.normalized,
            local_part=result.local_part,
            domain=result.domain
        )
        
    except EmailNotValidError as e:
        return EmailValidationResult(
            email=email,
            is_valid=False,
            error=str(e)
        )


def validate_emails_batch(
    emails: List[str],
    check_deliverability: bool = False,
    deduplicate: bool = True
) -> Tuple[List[EmailValidationResult], List[EmailValidationResult]]:
    """
    Validate a batch of email addresses.
    
    Args:
        emails: List of email addresses
        check_deliverability: Check DNS MX records
        deduplicate: Remove duplicates
        
    Returns:
        Tuple of (valid_results, invalid_results)
    """
    seen = set()
    valid = []
    invalid = []
    
    for email in emails:
        email = email.strip().lower() if email else ""
        
        # Skip empty
        if not email:
            continue
        
        # Skip duplicates
        if deduplicate:
            if email in seen:
                continue
            seen.add(email)
        
        result = validate_email(email, check_deliverability=check_deliverability)
        
        if result.is_valid:
            valid.append(result)
        else:
            invalid.append(result)
    
    logger.info(f"Validated {len(emails)} emails: {len(valid)} valid, {len(invalid)} invalid")
    
    return valid, invalid


def is_valid_email(email: str) -> bool:
    """
    Quick check if email is valid.
    
    Args:
        email: Email address to validate
        
    Returns:
        True if valid
    """
    return validate_email(email, check_deliverability=False).is_valid


def normalize_email(email: str) -> Optional[str]:
    """
    Normalize email address (lowercase, strip whitespace).
    
    Args:
        email: Email address
        
    Returns:
        Normalized email or None if invalid
    """
    result = validate_email(email.lower())
    return result.normalized_email if result.is_valid else None


def extract_domain(email: str) -> Optional[str]:
    """
    Extract domain from email address.
    
    Args:
        email: Email address
        
    Returns:
        Domain or None if invalid
    """
    result = validate_email(email)
    return result.domain if result.is_valid else None

