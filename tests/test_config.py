"""Tests for configuration management."""

import os
import pytest
import yaml
from unittest.mock import patch, mock_open
from pathlib import Path

from mercury.config import (
    expand_env_vars,
    load_yaml_config,
    merge_configs,
    create_default_config,
    SMTPConfig,
    UnifiedConfig,
    DEFAULT_CONFIG
)

# Test expand_env_vars

def test_expand_env_vars_simple(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "value")
    assert expand_env_vars("${TEST_VAR}") == "value"

def test_expand_env_vars_default():
    assert expand_env_vars("${MISSING:-default}") == "default"

def test_expand_env_vars_missing_no_default(caplog):
    assert expand_env_vars("${MISSING_VAR}") == "${MISSING_VAR}"
    assert "Environment variable MISSING_VAR not set" in caplog.text

def test_expand_env_vars_nested(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    data = {
        "key": "${API_KEY}",
        "list": ["val", "${API_KEY:-def}"],
        "nested": {"k": "${API_KEY}"}
    }
    expanded = expand_env_vars(data)
    assert expanded["key"] == "secret"
    assert expanded["list"][1] == "secret"
    assert expanded["nested"]["k"] == "secret"

def test_expand_env_vars_various_types():
    assert expand_env_vars(123) == 123
    assert expand_env_vars(None) is None

# Test merge_configs

def test_merge_configs_simple():
    c1 = {"a": 1, "b": 2}
    c2 = {"b": 3, "c": 4}
    merged = merge_configs(c1, c2)
    assert merged == {"a": 1, "b": 3, "c": 4}

def test_merge_configs_deep():
    c1 = {"nested": {"x": 1, "y": 2}}
    c2 = {"nested": {"y": 3, "z": 4}}
    merged = merge_configs(c1, c2)
    assert merged["nested"] == {"x": 1, "y": 3, "z": 4}

def test_merge_configs_none_ignored():
    c1 = {"a": 1}
    assert merge_configs(c1, None) == c1

# Test SMTPConfig

def test_smtp_config_defaults():
    data = {"host": "smtp.example.com"}
    config = SMTPConfig.from_dict(data)
    assert config.host == "smtp.example.com"
    assert config.port == 587
    assert config.name == "smtp.example.com"  # default to host if name missing

def test_smtp_config_override():
    data = {
        "name": "gmail",
        "host": "smtp.gmail.com",
        "port": 465,
        "use_ssl": True
    }
    config = SMTPConfig.from_dict(data)
    assert config.name == "gmail"
    assert config.port == 465
    assert config.use_ssl is True

# Test UnifiedConfig

def test_unified_config_from_dict_minimal():
    data = {
        "smtp": [{"host": "smtp.test"}],
        "email": {"from_email": "me@test.com", "subject": "Hi"},
        "template": {"html": "t.html"},
        "recipients": {"source": "r.csv"}
    }
    config = UnifiedConfig.from_dict(data)
    assert config.campaign_name == "Unnamed Campaign"
    assert len(config.smtp_providers) == 1
    assert config.smtp_providers[0].host == "smtp.test"

def test_unified_config_complex_parsing():
    data = {
        "campaign": {"name": "Test Campaign", "description": "Desc"},
        "email": {
            "subjects": [
                {"template": "Sub 1", "weight": 0.5},
                "Sub 2"  # Mixed types
            ]
        },
        "smtp_providers": {"host": "single.smtp"}  # Single dict support
    }
    config = UnifiedConfig.from_dict(data)
    assert config.campaign_name == "Test Campaign"
    assert len(config.smtp_providers) == 1
    assert config.smtp_providers[0].host == "single.smtp"
    assert config.email.subjects == ["Sub 1", "Sub 2"]
    assert config.email.subject == "Sub 1"

# Test Validation

def test_unified_config_validation(tmp_path):
    # Setup files
    tpl = tmp_path / "t.html"
    tpl.touch()
    rcpt = tmp_path / "r.csv"
    rcpt.touch()

    config = UnifiedConfig(
        smtp_providers=[SMTPConfig(name="s1", host="h1")],
        email=type('obj', (object,), {'from_email': 'f', 'subject': 's', 'subjects': []})(),
        template=type('obj', (object,), {'html': str(tpl), 'text': '', 'variants': []})(),
        recipients=type('obj', (object,), {'source': str(rcpt), 'email_column': 'e', 'validate': True, 'deduplicate': True})(),
        sending=type('obj', (object,), {'dry_run': True, 'concurrency': 1, 'chunk_size': 1, 'pause_between_chunks': 0, 'rate_per_minute': 0, 'rate_per_hour': 0})(),
        features=type('obj', (object,), {'qr_codes': False, 'send_as_image': False, 'pdf_attachments': False, 'docx_attachments': False, 'attachment_path': ''})()
    )
    # Re-construct proper objects using from_dict to be safe or manually access attributes if they match dataclass.
    # Actually UnifiedConfig takes dataclass instances.
    # Let's construct a valid config via from_dict for simplicity.
    
    valid_data = {
        "smtp": [{"host": "h"}],
        "email": {"from_email": "f", "subject": "s"},
        "template": {"html": str(tpl)},
        "recipients": {"source": str(rcpt)}
    }
    config = UnifiedConfig.from_dict(valid_data)
    assert not config.validate()

def test_unified_config_validation_failures():
    config = UnifiedConfig()
    errors = config.validate()
    assert "No SMTP providers configured" in errors
    assert "from_email is required" in errors
    assert "subject or subjects is required" in errors
    assert "template.html is required" in errors
    assert "recipients.source is required" in errors

def test_unified_config_validation_bad_smtp(tmp_path):
    data = {
        "smtp": [{"name": "bad", "host": ""}],  # Empty host
        "email": {"from_email": "f", "subject": "s"},
        "template": {"html": "t.html"},
        "recipients": {"source": "r.csv"}
    }
    config = UnifiedConfig.from_dict(data)
    errors = config.validate()
    assert any("host is required" in e for e in errors)

def test_unified_config_validation_missing_files(tmp_path):
    data = {
        "smtp": [{"host": "h"}],
        "email": {"from_email": "f", "subject": "s"},
        "template": {"html": str(tmp_path / "missing.html")},
        "recipients": {"source": str(tmp_path / "missing.csv")}
    }
    config = UnifiedConfig.from_dict(data)
    errors = config.validate()
    assert any("Template file not found" in e for e in errors)
    assert any("Recipients file not found" in e for e in errors)

# Test File Loading

def test_load_yaml_config(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("key: value\nnested:\n  k: v", encoding="utf-8")
    
    config = load_yaml_config(str(f))
    assert config["key"] == "value"
    assert config["nested"]["k"] == "v"

def test_load_yaml_config_missing():
    with pytest.raises(FileNotFoundError):
        load_yaml_config("nonexistent.yaml")

def test_unified_config_from_yaml(tmp_path):
    f = tmp_path / "campaign.yaml"
    content = """
    campaign:
      name: YAML Campaign
    smtp:
      - host: localhost
    """
    f.write_text(content, encoding="utf-8")
    
    config = UnifiedConfig.from_yaml(str(f))
    assert config.campaign_name == "YAML Campaign"

# Test Default Config Creation

def test_create_default_config(tmp_path):
    target = tmp_path / "campaign.yaml"
    created = create_default_config(str(target))
    
    assert created == str(target)
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "campaign:" in content
    assert "smtp_providers:" in content
