"""Tests for YAML configuration utilities.

The previous parallel ``MercuryConfig`` dataclass hierarchy and its tests
were removed during the Tier 1 #2 dataclass-collapse pass — those classes
were unused in src/. Coverage of the live config flow lives in
``test_services_coverage`` and ``test_config_dataclass_contract``.
"""

import pytest

from mercury.config import (
    expand_env_vars,
    load_yaml_config,
    merge_configs,
    create_default_config,
    DEFAULT_CONFIG,
)


# ---- expand_env_vars -------------------------------------------------------

def test_expand_env_vars_simple(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "value")
    assert expand_env_vars("${TEST_VAR}") == "value"


def test_expand_env_vars_default():
    assert expand_env_vars("${MISSING:-default}") == "default"


def test_expand_env_vars_missing_no_default(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    assert expand_env_vars("${MISSING_VAR}") == "${MISSING_VAR}"
    assert "Environment variable MISSING_VAR not set" in caplog.text


def test_expand_env_vars_nested(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    data = {
        "key": "${API_KEY}",
        "list": ["val", "${API_KEY:-def}"],
        "nested": {"k": "${API_KEY}"},
    }
    expanded = expand_env_vars(data)
    assert expanded["key"] == "secret"
    assert expanded["list"][1] == "secret"
    assert expanded["nested"]["k"] == "secret"


def test_expand_env_vars_passthrough_non_strings():
    assert expand_env_vars(123) == 123
    assert expand_env_vars(None) is None
    assert expand_env_vars(True) is True


# ---- merge_configs ---------------------------------------------------------

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


def test_merge_configs_replaces_non_dict_values():
    """When one side isn't a dict, later wins (no merging)."""
    assert merge_configs({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}
    assert merge_configs({"a": "str"}, {"a": {"x": 1}}) == {"a": {"x": 1}}


# ---- load_yaml_config ------------------------------------------------------

def test_load_yaml_config(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("key: value\nnested:\n  k: v", encoding="utf-8")

    config = load_yaml_config(str(f))
    assert config["key"] == "value"
    assert config["nested"]["k"] == "v"


def test_load_yaml_config_expands_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PASS", "topsecret")
    f = tmp_path / "config.yaml"
    f.write_text("db:\n  password: ${DB_PASS}\n", encoding="utf-8")

    config = load_yaml_config(str(f))
    assert config["db"]["password"] == "topsecret"


def test_load_yaml_config_missing():
    with pytest.raises(FileNotFoundError):
        load_yaml_config("nonexistent.yaml")


# ---- create_default_config -------------------------------------------------

def test_create_default_config_writes_template(tmp_path):
    target = tmp_path / "campaign.yaml"
    created = create_default_config(str(target))

    assert created == str(target)
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "campaign:" in content
    assert "smtp_providers:" in content


def test_default_config_template_is_valid_yaml():
    """Sanity: the embedded DEFAULT_CONFIG parses without error."""
    import yaml
    parsed = yaml.safe_load(DEFAULT_CONFIG)
    assert parsed["campaign"]["name"]
    assert parsed["smtp_providers"][0]["host"]
