"""Tests for placeholder processor."""

from mercury.features.placeholders import PlaceholderProcessor, generate_identity


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


def test_placeholder_first_name_tolerant_to_csv_column_capitalization():
    """{{first_name}} must resolve from common CSV column variants.

    The bug class this regression-guards: an operator's CSV uses any
    of the conventional spreadsheet capitalizations for the name
    column ('First Name', 'FirstName', 'First_Name', 'fname') and
    previously the placeholder silently fell back to the email-
    local-part derivation. They saw 'Support' (from support@x.com)
    instead of their CSV's 'Alice' and reported "the first_name
    placeholder doesn't work."
    """
    processor = PlaceholderProcessor()
    variants = [
        'first_name', 'First Name', 'FirstName', 'firstName',
        'First_Name', 'first-name', 'fname', 'given_name',
    ]
    for col in variants:
        result = processor.process(
            '{{first_name}}',
            {'email': 'support@example.com', col: 'Alice'},
        )
        assert result == 'Alice', (
            f"CSV column {col!r} should resolve to 'Alice' for "
            f"{{{{first_name}}}}, got {result!r}. Tolerant lookup "
            f"in get_builtin_placeholders is broken."
        )


def test_placeholder_company_tolerant_to_csv_column_capitalization():
    """Same fix surface as first_name — {{company}} must accept
    common spreadsheet capitalizations of the company column."""
    processor = PlaceholderProcessor()
    for col in ('company', 'Company', 'COMPANY', 'company_name', 'Organization', 'org'):
        result = processor.process(
            '{{company}}',
            {'email': 'a@example.com', col: 'Acme Inc'},
        )
        assert result == 'Acme Inc', (
            f"CSV column {col!r} should resolve {{{{company}}}} to 'Acme Inc', got {result!r}"
        )


def test_placeholder_first_name_local_part_fallback_still_works():
    """When no name column is provided, the email-local-part
    derivation must still kick in — keeps existing behavior for
    CSVs that only carry the email column."""
    processor = PlaceholderProcessor()
    result = processor.process('{{first_name}}', {'email': 'john.doe@example.com'})
    assert result == 'John', (
        f"local-part fallback regressed: got {result!r}, expected 'John'"
    )


def test_generate_identity():
    """Test identity generation."""
    identity = generate_identity()
    
    assert "first_name" in identity
    assert "last_name" in identity
    assert "email" in identity
    assert "uuid" in identity
    assert "@" in identity["email"]

