"""Tests for custom exceptions."""

import pytest

from mercury.exceptions import (
    MercuryException,
    SMTPException,
    TransientSMTPError,
    PermanentSMTPError,
    SMTPConnectionError,
    SMTPAuthenticationError,
    ValidationException,
    InvalidEmailError,
    ConfigurationException,
    RateLimitException,
    is_transient_error,
    categorize_exception
)


class TestExceptionHierarchy:
    """Test exception class hierarchy."""
    
    def test_base_exception(self):
        """Test base exception."""
        exc = MercuryException("Test error", details={'key': 'value'})
        
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
        assert exc.details == {'key': 'value'}
    
    def test_exception_to_dict(self):
        """Test exception serialization."""
        exc = ValidationException("Validation failed", details={'field': 'email'})
        
        data = exc.to_dict()
        
        assert data['error_type'] == 'ValidationException'
        assert data['message'] == "Validation failed"
        assert data['details']['field'] == 'email'
    
    def test_smtp_exception_attributes(self):
        """Test SMTP exception attributes."""
        exc = SMTPException(
            "SMTP error",
            smtp_server="smtp.example.com",
            smtp_response="550 Error",
            is_transient=True
        )
        
        assert exc.smtp_server == "smtp.example.com"
        assert exc.smtp_response == "550 Error"
        assert exc.is_transient is True
    
    def test_transient_smtp_error(self):
        """Test transient SMTP error."""
        exc = TransientSMTPError("Temporary failure")
        
        assert exc.is_transient is True
        assert isinstance(exc, SMTPException)
    
    def test_permanent_smtp_error(self):
        """Test permanent SMTP error."""
        exc = PermanentSMTPError("Permanent failure")
        
        assert exc.is_transient is False
        assert isinstance(exc, SMTPException)
    
    def test_rate_limit_exception(self):
        """Test rate limit exception."""
        exc = RateLimitException("Rate limit exceeded", retry_after=60.0)
        
        assert exc.retry_after == 60.0
        assert exc.details['retry_after'] == 60.0


class TestExceptionUtilities:
    """Test exception utility functions."""
    
    def test_is_transient_error_transient(self):
        """Test identifying transient errors."""
        exc = TransientSMTPError("Temp error")
        
        assert is_transient_error(exc) is True
    
    def test_is_transient_error_permanent(self):
        """Test identifying permanent errors."""
        exc = PermanentSMTPError("Perm error")
        
        assert is_transient_error(exc) is False
    
    def test_is_transient_error_connection(self):
        """Test connection errors are transient."""
        exc = ConnectionError("Connection failed")
        
        assert is_transient_error(exc) is True
    
    def test_is_transient_error_rate_limit(self):
        """Test rate limit errors are transient."""
        exc = RateLimitException("Too many requests")
        
        assert is_transient_error(exc) is True
    
    def test_categorize_exception_smtp(self):
        """Test exception categorization."""
        exc = SMTPConnectionError("Connection failed")
        category = categorize_exception(exc)
        
        assert category == 'smtp_error'
    
    def test_categorize_exception_validation(self):
        """Test validation exception categorization."""
        exc = ValidationException("Invalid input")
        category = categorize_exception(exc)
        
        assert category == 'validation_error'
    
    def test_categorize_exception_config(self):
        """Test config exception categorization."""
        exc = ConfigurationException("Bad config")
        category = categorize_exception(exc)
        
        assert category == 'configuration_error'
    
    def test_categorize_exception_unknown(self):
        """Test unknown exception categorization."""
        exc = ValueError("Some error")
        category = categorize_exception(exc)
        
        assert category == 'unknown_error'

