"""Tests for placeholder processor."""

import pytest
from unified_sender.features.placeholders import PlaceholderProcessor, generate_identity


def test_placeholder_processor_basic():
    """Test basic placeholder replacement."""
    processor = PlaceholderProcessor()
    
    template = "Hello {{first_name}}, your email is {{email}}"
    result = processor.process(template, {"email": "john.doe@example.com"})
    
    assert "john.doe@example.com" in result
    assert "John" in result  # Extracted from email


def test_placeholder_processor_date():
    """Test date placeholders."""
    processor = PlaceholderProcessor()
    
    template = "Today is {{date_formatted}}, year {{year}}"
    result = processor.process(template)
    
    assert "{{date_formatted}}" not in result
    assert "{{year}}" not in result


def test_placeholder_processor_static():
    """Test static placeholders."""
    processor = PlaceholderProcessor({"company": "Acme Inc"})
    
    template = "Welcome to {{company}}"
    result = processor.process(template)
    
    assert result == "Welcome to Acme Inc"


def test_get_used_placeholders():
    """Test extracting used placeholders."""
    processor = PlaceholderProcessor()
    
    template = "Hello {{first_name}}, your email {{email}} at {{company}}"
    used = processor.get_used_placeholders(template)
    
    assert "first_name" in used
    assert "email" in used
    assert "company" in used


def test_validate_placeholders():
    """Test placeholder validation."""
    processor = PlaceholderProcessor()
    
    template = "Hello {{first_name}}, your {{custom_field}} is ready"
    result = processor.validate_placeholders(template)
    
    assert "first_name" in result["used"]
    assert "custom_field" in result["used"]


def test_generate_identity():
    """Test identity generation."""
    identity = generate_identity()
    
    assert "first_name" in identity
    assert "last_name" in identity
    assert "email" in identity
    assert "uuid" in identity
    assert "@" in identity["email"]

