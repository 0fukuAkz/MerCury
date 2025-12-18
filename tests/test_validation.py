"""Tests for validation utilities."""

import pytest
from pathlib import Path

from unified_sender.utils.validation import (
    validate_email,
    validate_emails_batch,
    is_valid_email,
    normalize_email,
    extract_domain,
    EmailValidationResult
)
from unified_sender.utils.validators import (
    validate_file_path,
    validate_url,
    validate_port,
    validate_positive_int,
    validate_rate_limit,
    validate_concurrency
)
from unified_sender.exceptions import ValidationException, InvalidConfigValueError


class TestEmailValidation:
    """Test email validation functions."""
    
    def test_valid_email(self):
        """Test validating correct email."""
        result = validate_email("user@example.com")
        
        assert result.is_valid is True
        assert result.normalized_email == "user@example.com"
        assert result.domain == "example.com"
        assert result.local_part == "user"
    
    def test_invalid_email_format(self):
        """Test invalid email format."""
        result = validate_email("not-an-email")
        
        assert result.is_valid is False
        assert result.error is not None
    
    def test_empty_email(self):
        """Test empty email."""
        result = validate_email("")
        
        assert result.is_valid is False
        assert "Empty" in result.error
    
    def test_email_with_plus(self):
        """Test email with + sign."""
        result = validate_email("user+tag@example.com")
        
        assert result.is_valid is True
        assert result.local_part == "user+tag"
    
    def test_is_valid_email_helper(self):
        """Test quick validation helper."""
        assert is_valid_email("user@example.com") is True
        assert is_valid_email("invalid") is False
    
    def test_normalize_email(self):
        """Test email normalization."""
        normalized = normalize_email("  USER@EXAMPLE.COM  ")
        
        assert normalized == "user@example.com"
    
    def test_extract_domain(self):
        """Test domain extraction."""
        domain = extract_domain("user@example.com")
        
        assert domain == "example.com"
    
    def test_validate_emails_batch(self):
        """Test batch validation."""
        emails = [
            "valid1@example.com",
            "valid2@example.com",
            "invalid",
            "",
            "valid3@example.com"
        ]
        
        valid, invalid = validate_emails_batch(emails)
        
        assert len(valid) == 3
        assert len(invalid) == 1  # Only "invalid" counted, empty skipped
    
    def test_validate_emails_batch_dedupe(self):
        """Test batch validation with deduplication."""
        emails = [
            "user@example.com",
            "user@example.com",  # Duplicate
            "other@example.com"
        ]
        
        valid, invalid = validate_emails_batch(emails, deduplicate=True)
        
        assert len(valid) == 2  # Duplicate removed


class TestFileValidation:
    """Test file path validation."""
    
    def test_validate_existing_file(self, tmp_path):
        """Test validating existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        
        validated = validate_file_path(str(test_file))
        
        assert validated == test_file
        assert validated.exists()
    
    def test_validate_missing_file(self):
        """Test validating non-existent file."""
        with pytest.raises(ValidationException, match="does not exist"):
            validate_file_path("/nonexistent/file.txt", must_exist=True)
    
    def test_validate_empty_path(self):
        """Test empty path validation."""
        with pytest.raises(ValidationException, match="cannot be empty"):
            validate_file_path("")


class TestURLValidation:
    """Test URL validation."""
    
    def test_valid_http_url(self):
        """Test valid HTTP URL."""
        url = validate_url("http://example.com/path")
        
        assert url == "http://example.com/path"
    
    def test_valid_https_url(self):
        """Test valid HTTPS URL."""
        url = validate_url("https://example.com")
        
        assert url == "https://example.com"
    
    def test_require_https(self):
        """Test HTTPS requirement."""
        with pytest.raises(ValidationException, match="must use HTTPS"):
            validate_url("http://example.com", require_https=True)
    
    def test_invalid_url(self):
        """Test invalid URL format."""
        with pytest.raises(ValidationException, match="Invalid URL"):
            validate_url("not-a-url")
    
    def test_localhost_url(self):
        """Test localhost URL."""
        url = validate_url("http://localhost:8000")
        
        assert url == "http://localhost:8000"


class TestPortValidation:
    """Test port number validation."""
    
    def test_valid_port(self):
        """Test valid port number."""
        port = validate_port(8080, allow_privileged=False)
        
        assert port == 8080
    
    def test_privileged_port_not_allowed(self):
        """Test privileged port rejection."""
        with pytest.raises(InvalidConfigValueError, match="Privileged port"):
            validate_port(80, allow_privileged=False)
    
    def test_privileged_port_allowed(self):
        """Test allowing privileged port."""
        port = validate_port(80, allow_privileged=True)
        
        assert port == 80
    
    def test_invalid_port_range(self):
        """Test out-of-range port."""
        with pytest.raises(InvalidConfigValueError, match="out of valid range"):
            validate_port(99999)
    
    def test_negative_port(self):
        """Test negative port number."""
        with pytest.raises(InvalidConfigValueError):
            validate_port(-1, allow_privileged=True)


class TestRateLimitValidation:
    """Test rate limit validation."""
    
    def test_valid_rate_limits(self):
        """Test valid rate limit configuration."""
        per_minute, per_hour = validate_rate_limit(60, 1000)
        
        assert per_minute == 60
        assert per_hour == 1000
    
    def test_negative_per_minute(self):
        """Test negative per_minute."""
        with pytest.raises(InvalidConfigValueError):
            validate_rate_limit(-1, 1000)
    
    def test_inconsistent_limits(self, caplog):
        """Test warning for inconsistent limits."""
        validate_rate_limit(100, 1000)  # 100/min * 60 = 6000/hour > 1000
        
        # Should log warning
        assert "exceeds per_hour" in caplog.text


class TestConcurrencyValidation:
    """Test concurrency validation."""
    
    def test_valid_concurrency(self):
        """Test valid concurrency value."""
        value = validate_concurrency(50)
        
        assert value == 50
    
    def test_zero_concurrency(self):
        """Test zero concurrency."""
        with pytest.raises(InvalidConfigValueError, match="must be >= 1"):
            validate_concurrency(0)
    
    def test_excessive_concurrency(self):
        """Test excessive concurrency."""
        with pytest.raises(InvalidConfigValueError, match="exceeds maximum"):
            validate_concurrency(5000, max_concurrency=1000)


class TestPositiveIntValidation:
    """Test positive integer validation."""
    
    def test_valid_positive_int(self):
        """Test valid positive integer."""
        value = validate_positive_int(10, "count")
        
        assert value == 10
    
    def test_zero_value(self):
        """Test zero value."""
        with pytest.raises(InvalidConfigValueError):
            validate_positive_int(0, "count", min_value=1)
    
    def test_negative_value(self):
        """Test negative value."""
        with pytest.raises(InvalidConfigValueError):
            validate_positive_int(-5, "count")
    
    def test_custom_min_value(self):
        """Test custom minimum value."""
        value = validate_positive_int(10, "count", min_value=5)
        
        assert value == 10
        
        with pytest.raises(InvalidConfigValueError):
            validate_positive_int(3, "count", min_value=5)

