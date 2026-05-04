"""YAML configuration utilities.

This module previously held a parallel ``MercuryConfig`` dataclass hierarchy
(with sub-configs for SMTP, email, templates, recipients, sending, features)
that nothing in src/ ever imported — the live config flow runs through
``services.campaign_service.CampaignConfig`` (built by ``load_campaign_from_yaml``)
projected to ``services.email_service.EmailConfig`` for the sender.

The dead hierarchy was removed during the Tier 1 #2 dataclass-collapse pass.
What remains here are the genuinely-shared YAML helpers used by both the CLI
loader and the ``mercury new`` scaffolding command.
"""

import os
import re
import logging
from typing import Any, Dict
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def expand_env_vars(value: Any) -> Any:
    """
    Recursively expand environment variables in configuration values.

    Supports:
      - ``${VAR_NAME}`` — required variable; left as-is and a warning is
        logged if the variable is unset.
      - ``${VAR_NAME:-default}`` — variable with a fallback default.
    """
    if isinstance(value, str):
        pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'

        def replace(match):
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            if default is not None:
                return default
            logger.warning(
                f"Environment variable {var_name} not set and no default provided"
            )
            return match.group(0)

        return re.sub(pattern, replace, value)

    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}

    if isinstance(value, list):
        return [expand_env_vars(item) for item in value]

    return value


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """
    Load and parse a YAML configuration file, expanding env vars in values.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    config = expand_env_vars(config)
    logger.info(f"Loaded configuration from {config_path}")
    return config


def merge_configs(*configs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge multiple configuration dicts. Later configs override earlier ones.
    """
    result: Dict[str, Any] = {}
    for config in configs:
        if config is None:
            continue
        for key, value in config.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_configs(result[key], value)
            else:
                result[key] = value
    return result


# Default configuration template emitted by `mercury new project`.
DEFAULT_CONFIG = """
# MerCury Email Platform - Campaign Configuration
# Documentation: https://github.com/mercury/mercury

campaign:
  name: "My Email Campaign"
  description: "Campaign description"

smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: ${SMTP_USER}
    password: ${SMTP_PASS}
    use_tls: true
    weight: 1.0
    max_per_minute: 30
    max_per_hour: 500

email:
  subject: "Hello {{first_name}}!"
  subjects:
    - template: "Hello {{first_name}}!"
      weight: 0.5
    - template: "Important Update"
      weight: 0.5
  from_email: sender@example.com
  from_name: "Your Company"
  reply_to: reply@example.com

template:
  html: templates/email.html

recipients:
  source: data/recipients.csv
  email_column: email
  validate: true
  deduplicate: true

links:
  - "https://example.com/link1"
  - "https://example.com/link2"
  - "https://example.com/link3"

placeholders:
  path: config/placeholders.yaml
  static:
    company_name: "Your Company"
    support_email: "support@example.com"

sending:
  dry_run: true
  concurrency: 50
  chunk_size: 1000
  rate_per_minute: 30
  rate_per_hour: 500
  pause_between_chunks: 30

features:
  qr_codes: false
  send_as_image: false
  pdf_attachments: false
"""


def create_default_config(path: str = "config/campaign.yaml") -> str:
    """
    Write the default campaign config to ``path``. Used by ``mercury new``.
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(DEFAULT_CONFIG.strip())
    return path
