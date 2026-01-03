
import os
import pytest
import yaml
from mercury.features.template_engine import TemplateEngine, TemplateConfig

def test_load_placeholders_from_yaml(tmp_path):
    """Test that TemplateEngine loads placeholders from a YAML file."""
    # 1. Create a dummy placeholders.yaml
    yaml_content = {
        "test_key": "test_value_123",
        "company_name": "Acme Corp"
    }
    placeholders_file = tmp_path / "placeholders.yaml"
    with open(placeholders_file, "w") as f:
        yaml.dump(yaml_content, f)
        
    # 2. Init engine with this file and template content
    engine = TemplateEngine(
        placeholders_path=str(placeholders_file),
        html_content="Hello from {{company_name}}. ID: {{test_key}}"
    )
    
    # 3. Verify loading
    assert engine._static_placeholders["test_key"] == "test_value_123"
    assert engine._static_placeholders["company_name"] == "Acme Corp"
    
    # 4. Verify rendering
    result = engine.render()
    
    assert "Hello from Acme Corp" in result
    assert "ID: test_value_123" in result

def test_load_placeholders_nonexistent_file():
    """Test graceful failure for missing file."""
    engine = TemplateEngine(
        placeholders_path="nonexistent_file.yaml"
    )
    # Should not crash, just empty dict
    assert engine._static_placeholders == {}
