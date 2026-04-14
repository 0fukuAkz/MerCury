"""Template engine with full placeholder and feature support."""

import os
import re
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .placeholders import PlaceholderProcessor
from .generators import QRCodeGenerator, GeneratorConfig

logger = logging.getLogger(__name__)


@dataclass
class TemplateConfig:
    """Template engine configuration."""
    template_path: Optional[str] = None
    html_content: Optional[str] = None
    placeholders_path: Optional[str] = None
    enable_qr_code: bool = False
    qr_link: Optional[str] = None


class TemplateEngine:
    """
    Template engine with placeholder processing and content generation.
    
    Supports:
    - HTML templates from files or strings
    - 50+ built-in placeholders
    - QR code embedding
    - Conditional content blocks
    - Template includes
    """
    
    def __init__(
        self,
        config: Optional[TemplateConfig] = None,
        template_path: Optional[str] = None,
        html_content: Optional[str] = None,
        placeholders_path: Optional[str] = None
    ):
        """
        Initialize template engine.
        
        Args:
            config: Template configuration
            template_path: Path to HTML template file
            html_content: Direct HTML content
            placeholders_path: Path to placeholders JSON/YAML file
        """
        if config:
            self.config = config
        else:
            self.config = TemplateConfig(
                template_path=template_path,
                html_content=html_content,
                placeholders_path=placeholders_path
            )
        
        self._template_content: Optional[str] = None
        self._static_placeholders: Dict[str, str] = {}
        
        # Initialize components
        self._load_template()
        self._load_static_placeholders()
        
        self.placeholder_processor = PlaceholderProcessor(self._static_placeholders)
        self.qr_generator = QRCodeGenerator(GeneratorConfig())
    
    def _load_template(self):
        """Load template content."""
        if self.config.html_content:
            self._template_content = self.config.html_content
        elif self.config.template_path and os.path.exists(self.config.template_path):
            try:
                with open(self.config.template_path, 'r', encoding='utf-8') as f:
                    self._template_content = f.read()
                logger.debug(f"Loaded template from {self.config.template_path}")
            except Exception as e:
                logger.error(f"Failed to load template: {e}")
                self._template_content = ""
        else:
            self._template_content = ""
    
    def _load_static_placeholders(self):
        """Load static placeholders from file."""
        if not self.config.placeholders_path:
            return
        
        if not os.path.exists(self.config.placeholders_path):
            return
        
        try:
            import json
            import yaml
            
            with open(self.config.placeholders_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if self.config.placeholders_path.endswith(('.yaml', '.yml')):
                self._static_placeholders = yaml.safe_load(content) or {}
            else:
                self._static_placeholders = json.loads(content)
            
            logger.debug(f"Loaded {len(self._static_placeholders)} static placeholders")
            
        except Exception as e:
            logger.error(f"Failed to load placeholders: {e}")
    
    def set_template(self, html_content: str):
        """Set template content directly."""
        self._template_content = html_content
    
    def load_template(self, template_path: str):
        """Load template from file."""
        self.config.template_path = template_path
        self._load_template()
    
    def add_static_placeholder(self, key: str, value: str):
        """Add a static placeholder value."""
        self._static_placeholders[key] = value
        self.placeholder_processor.static_placeholders[key] = value
    
    def render(
        self,
        recipient: Optional[str] = None,
        recipient_data: Optional[Dict[str, Any]] = None,
        extra_placeholders: Optional[Dict[str, str]] = None,
        qr_code_data_url: Optional[str] = None,
        link: Optional[str] = None
    ) -> str:
        """
        Render template with all placeholders replaced.
        
        Args:
            recipient: Recipient email address
            recipient_data: Additional recipient data
            extra_placeholders: Extra placeholder values
            qr_code_data_url: Pre-generated QR code data URL
            link: Link for QR code and {{link}} placeholder
            
        Returns:
            Rendered HTML string
        """
        if not self._template_content:
            logger.warning("No template content loaded")
            return ""
        
        # Build recipient data
        data = recipient_data or {}
        if recipient:
            data['email'] = recipient
        
        # Build extra placeholders
        extras = extra_placeholders or {}
        
        # Add link placeholder
        if link:
            extras['link'] = link
            extras['url'] = link
        
        # Generate or add QR code
        if qr_code_data_url:
            extras['qr_code'] = f'<img src="{qr_code_data_url}" alt="QR Code" />'
            extras['qr_code_url'] = qr_code_data_url
        elif self.config.enable_qr_code and (link or self.config.qr_link):
            qr_link = link or self.config.qr_link
            qr_data_url = self.qr_generator.generate_data_url(qr_link)
            extras['qr_code'] = f'<img src="{qr_data_url}" alt="QR Code" />'
            extras['qr_code_url'] = qr_data_url
        
        # Process template
        html = self._template_content
        
        # Process includes first
        html = self._process_includes(html)
        
        # Process conditionals
        html = self._process_conditionals(html, data, extras)
        
        # Process placeholders
        html = self.placeholder_processor.process(html, data, extras)
        
        return html
    
    def _process_includes(self, html: str) -> str:
        """
        Process template includes.
        
        Syntax: {{include:path/to/file.html}}
        """
        pattern = r'\{\{include:([^}]+)\}\}'
        
        def replace_include(match):
            include_path = match.group(1).strip()
            
            # Resolve relative to template directory
            if self.config.template_path:
                base_dir = os.path.dirname(self.config.template_path)
                full_path = os.path.join(base_dir, include_path)
            else:
                full_path = include_path
            
            if os.path.exists(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    logger.warning(f"Failed to include {include_path}: {e}")
            
            return match.group(0)
        
        return re.sub(pattern, replace_include, html)
    
    def _process_conditionals(
        self,
        html: str,
        recipient_data: Dict[str, Any],
        extra_placeholders: Dict[str, str]
    ) -> str:
        """
        Process conditional blocks.
        
        Syntax: 
        {{if:placeholder}}content{{endif}}
        {{if:placeholder}}content{{else}}alt_content{{endif}}
        """
        # Combine all placeholder values
        all_values = {}
        all_values.update(self.placeholder_processor.get_builtin_placeholders(recipient_data))
        all_values.update(self._static_placeholders)
        all_values.update(extra_placeholders)
        
        # Process if/else/endif blocks
        pattern = r'\{\{if:([^}]+)\}\}(.*?)(?:\{\{else\}\}(.*?))?\{\{endif\}\}'
        
        def replace_conditional(match):
            condition = match.group(1).strip()
            if_content = match.group(2)
            else_content = match.group(3) or ''
            
            # Check if condition is truthy
            value = all_values.get(condition, '')
            is_true = bool(value) and value.lower() not in ('false', '0', 'no', 'none')
            
            return if_content if is_true else else_content
        
        # Process multiple times for nested conditionals
        max_iterations = 10
        for _ in range(max_iterations):
            new_html = re.sub(pattern, replace_conditional, html, flags=re.DOTALL)
            if new_html == html:
                break
            html = new_html
        
        return html
    
    def validate(self) -> Dict[str, Any]:
        """
        Validate template and return analysis.
        
        Returns:
            Dict with validation results
        """
        if not self._template_content:
            return {
                'valid': False,
                'error': 'No template content loaded',
                'placeholders': []
            }
        
        result = self.placeholder_processor.validate_placeholders(self._template_content)
        result['template_path'] = self.config.template_path
        result['template_size'] = len(self._template_content)
        
        return result
    
    def get_used_placeholders(self) -> List[str]:
        """Get list of placeholders used in template."""
        if not self._template_content:
            return []
        return self.placeholder_processor.get_used_placeholders(self._template_content)
    
    def preview(
        self,
        recipient: str = "test@example.com",
        extra_placeholders: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Generate preview with sample data.
        
        Args:
            recipient: Sample recipient email
            extra_placeholders: Additional placeholder values
            
        Returns:
            Rendered HTML preview
        """
        return self.render(
            recipient=recipient,
            extra_placeholders=extra_placeholders,
            link="https://example.com/preview"
        )


def load_template(template_path: str) -> str:
    """Load template from file."""
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load template {template_path}: {e}")
        return ""

