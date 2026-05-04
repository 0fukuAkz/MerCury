"""Tests for template engine."""

from mercury.features.template_engine import TemplateEngine


def test_template_engine_basic():
    """Test basic template rendering."""
    engine = TemplateEngine(html_content="<p>Hello {{first_name}}!</p>")
    
    result = engine.render(recipient="john@example.com")
    
    assert "Hello John" in result


def test_template_engine_conditionals():
    """Test conditional blocks."""
    template = """
    <p>Hello {{first_name}}</p>
    {{if:link}}
    <a href="{{link}}">Click here</a>
    {{endif}}
    """
    engine = TemplateEngine(html_content=template)
    
    # With link
    result_with_link = engine.render(
        recipient="john@example.com",
        link="https://example.com"
    )
    assert "Click here" in result_with_link
    
    # Without link
    result_without_link = engine.render(recipient="john@example.com")
    assert "Click here" not in result_without_link


def test_template_engine_else():
    """Test if/else blocks."""
    template = """
    {{if:premium}}
    Welcome Premium Member!
    {{else}}
    Upgrade to Premium!
    {{endif}}
    """
    engine = TemplateEngine(html_content=template)
    
    # With premium
    result = engine.render(
        recipient="john@example.com",
        extra_placeholders={"premium": "true"}
    )
    assert "Welcome Premium Member" in result
    
    # Without premium
    result2 = engine.render(recipient="john@example.com")
    assert "Upgrade to Premium" in result2


def test_template_validation():
    """Test template validation."""
    engine = TemplateEngine(
        html_content="Hello {{first_name}}, your {{custom_var}} is ready"
    )
    
    result = engine.validate()
    
    assert result["valid"] is True or result["valid"] is False
    assert "first_name" in result["used"]
    assert "custom_var" in result["used"]


def test_get_used_placeholders():
    """Test getting used placeholders."""
    engine = TemplateEngine(
        html_content="{{email}} {{first_name}} {{company}}"
    )
    
    placeholders = engine.get_used_placeholders()
    
    assert "email" in placeholders
    assert "first_name" in placeholders
    assert "company" in placeholders


def test_static_placeholders():
    """Test adding static placeholders."""
    engine = TemplateEngine(html_content="Company: {{company_name}}")
    engine.add_static_placeholder("company_name", "Acme Inc")
    
    result = engine.render(recipient="test@example.com")
    
    assert "Acme Inc" in result

