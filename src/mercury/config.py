"""Configuration management with YAML support and environment variable expansion."""

import os
import re
import logging
from typing import Dict, Any, List
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def expand_env_vars(value: Any) -> Any:
    """
    Recursively expand environment variables in configuration values.
    
    Supports:
    - ${VAR_NAME} - Required variable
    - ${VAR_NAME:-default} - Variable with default
    """
    if isinstance(value, str):
        # Pattern for ${VAR_NAME} or ${VAR_NAME:-default}
        pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'
        
        def replace(match):
            var_name = match.group(1)
            default = match.group(2)
            
            env_value = os.environ.get(var_name)
            
            if env_value is not None:
                return env_value
            elif default is not None:
                return default
            else:
                logger.warning(f"Environment variable {var_name} not set and no default provided")
                return match.group(0)
        
        return re.sub(pattern, replace, value)
    
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    
    elif isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    
    return value


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """
    Load and parse YAML configuration file.
    
    Args:
        config_path: Path to YAML file
        
    Returns:
        Parsed configuration dict
    """
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Expand environment variables
    config = expand_env_vars(config)
    
    logger.info(f"Loaded configuration from {config_path}")
    
    return config


def merge_configs(*configs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge multiple configuration dicts.
    
    Later configs override earlier ones.
    """
    result = {}
    
    for config in configs:
        if config is None:
            continue
        
        for key, value in config.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_configs(result[key], value)
            else:
                result[key] = value
    
    return result


@dataclass
class SMTPConfig:
    """SMTP server configuration."""
    name: str
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    use_auth: bool = True
    timeout: int = 30
    from_email: str = ""
    from_name: str = ""
    weight: float = 1.0
    priority: int = 0
    max_per_minute: int = 30
    max_per_hour: int = 500
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SMTPConfig':
        """Create from dictionary."""
        return cls(
            name=data.get('name', data.get('host', 'default')),
            host=data['host'],
            port=data.get('port', 587),
            username=data.get('username', ''),
            password=data.get('password', ''),
            use_tls=data.get('use_tls', True),
            use_ssl=data.get('use_ssl', False),
            use_auth=data.get('use_auth', True),
            timeout=data.get('timeout', 30),
            from_email=data.get('from_email', ''),
            from_name=data.get('from_name', ''),
            weight=data.get('weight', 1.0),
            priority=data.get('priority', 0),
            max_per_minute=data.get('max_per_minute', 30),
            max_per_hour=data.get('max_per_hour', 500)
        )


@dataclass
class EmailConfig:
    """Email content configuration."""
    subject: str = ""
    subjects: List[str] = field(default_factory=list)
    from_email: str = ""
    from_name: str = ""
    from_names: List[str] = field(default_factory=list)
    reply_to: str = ""


@dataclass
class TemplateConfig:
    """Template configuration."""
    html: str = ""
    text: str = ""
    variants: List[str] = field(default_factory=list)


@dataclass
class RecipientsConfig:
    """Recipients configuration."""
    source: str = ""
    email_column: str = "email"
    validate: bool = True
    deduplicate: bool = True


@dataclass
class SendingConfig:
    """Sending options configuration."""
    dry_run: bool = False
    concurrency: int = 50
    chunk_size: int = 1000
    pause_between_chunks: int = 0
    rate_per_minute: int = 0
    rate_per_hour: int = 0


@dataclass
class FeaturesConfig:
    """Features configuration."""
    qr_codes: bool = False
    send_as_image: bool = False
    pdf_attachments: bool = False
    docx_attachments: bool = False
    attachment_path: str = ""


@dataclass
class MercuryConfig:
    """Complete mercury configuration."""
    campaign_name: str = "Unnamed Campaign"
    campaign_description: str = ""
    
    smtp_providers: List[SMTPConfig] = field(default_factory=list)
    email: EmailConfig = field(default_factory=EmailConfig)
    template: TemplateConfig = field(default_factory=TemplateConfig)
    recipients: RecipientsConfig = field(default_factory=RecipientsConfig)
    sending: SendingConfig = field(default_factory=SendingConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    
    links: List[str] = field(default_factory=list)
    
    placeholders_path: str = "config/placeholders.yaml"
    placeholders: Dict[str, str] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MercuryConfig':
        """Create from dictionary."""
        campaign = data.get('campaign', {})
        email = data.get('email', {})
        template = data.get('template', {})
        recipients = data.get('recipients', {})
        sending = data.get('sending', {})
        features = data.get('features', {})
        
        # Parse SMTP providers
        smtp_data = data.get('smtp_providers', data.get('smtp', []))
        if isinstance(smtp_data, dict):
            smtp_data = [smtp_data]
        smtp_providers = [SMTPConfig.from_dict(s) for s in smtp_data]
        
        # Parse subjects
        subjects = email.get('subjects', [])
        if subjects and isinstance(subjects[0], dict):
            subjects = [s.get('template', s) if isinstance(s, dict) else s for s in subjects]
        
        return cls(
            campaign_name=campaign.get('name', 'Unnamed Campaign'),
            campaign_description=campaign.get('description', ''),
            
            smtp_providers=smtp_providers,
            
            email=EmailConfig(
                subject=email.get('subject', subjects[0] if subjects else ''),
                subjects=subjects,
                from_email=email.get('from_email', ''),
                from_name=email.get('from_name', ''),
                from_names=email.get('from_names', []),
                reply_to=email.get('reply_to', '')
            ),
            
            template=TemplateConfig(
                html=template.get('html', template.get('path', '')),
                text=template.get('text', ''),
                variants=template.get('variants', [])
            ),
            
            recipients=RecipientsConfig(
                source=recipients.get('source', recipients.get('path', '')),
                email_column=recipients.get('email_column', 'email'),
                validate=recipients.get('validate', True),
                deduplicate=recipients.get('deduplicate', True)
            ),
            
            sending=SendingConfig(
                dry_run=sending.get('dry_run', data.get('dry_run', False)),
                concurrency=sending.get('concurrency', 50),
                chunk_size=sending.get('chunk_size', 1000),
                pause_between_chunks=sending.get('pause_between_chunks', 0),
                rate_per_minute=sending.get('rate_per_minute', 0),
                rate_per_hour=sending.get('rate_per_hour', 0)
            ),
            
            features=FeaturesConfig(
                qr_codes=features.get('qr_codes', False),
                send_as_image=features.get('send_as_image', False),
                pdf_attachments=features.get('pdf_attachments', False),
                docx_attachments=features.get('docx_attachments', False),
                attachment_path=features.get('attachment_path', '')
            ),
            
            links=data.get('links', []),
            
            placeholders_path=data.get('placeholders', {}).get('path', 'config/placeholders.yaml'),
            placeholders=data.get('placeholders', {}).get('static', {})
        )
    
    @classmethod
    def from_yaml(cls, config_path: str) -> 'MercuryConfig':
        """Load configuration from YAML file."""
        data = load_yaml_config(config_path)
        return cls.from_dict(data)
    
    def validate(self) -> List[str]:
        """
        Validate configuration.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not self.smtp_providers:
            errors.append("No SMTP providers configured")
        
        for i, smtp in enumerate(self.smtp_providers):
            if not smtp.host:
                errors.append(f"SMTP provider {i}: host is required")
        
        if not self.email.from_email:
            errors.append("from_email is required")
        
        if not self.email.subject and not self.email.subjects:
            errors.append("subject or subjects is required")
        
        if not self.template.html:
            errors.append("template.html is required")
        elif not os.path.exists(self.template.html):
            errors.append(f"Template file not found: {self.template.html}")
        
        if not self.recipients.source:
            errors.append("recipients.source is required")
        elif not os.path.exists(self.recipients.source):
            errors.append(f"Recipients file not found: {self.recipients.source}")
        
        return errors


# Default configuration template
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
    Create a default configuration file.
    
    Args:
        path: Path to save configuration
        
    Returns:
        Path to created file
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(DEFAULT_CONFIG.strip())
    
    return path

