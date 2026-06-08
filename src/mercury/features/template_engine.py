"""Template engine with full placeholder and feature support."""

import os
import re
import logging
import random
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
        placeholders_path: Optional[str] = None,
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
                placeholders_path=placeholders_path,
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
                with open(self.config.template_path, "r", encoding="utf-8") as f:
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

            with open(self.config.placeholders_path, "r", encoding="utf-8") as f:
                content = f.read()

            if self.config.placeholders_path.endswith((".yaml", ".yml")):
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
        link: Optional[str] = None,
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

        # Build recipient data — copy first so we don't mutate the caller's
        # dict (which would leak the email field back into a reused
        # recipients list and cross-contaminate the next render).
        data: Dict[str, Any] = dict(recipient_data) if recipient_data else {}
        if recipient:
            data["email"] = recipient

        # Build extra placeholders
        extras = extra_placeholders or {}

        # Add link placeholder (always provide key so {{link}} resolves)
        extras["link"] = link or ""
        extras["url"] = link or ""

        # Always define qr_code / qr_code_url (empty string when not generated)
        # so the placeholder processor never leaves a literal "{{qr_code}}" in
        # the rendered email when QR is disabled or has no link.
        extras.setdefault("qr_code", "")
        extras.setdefault("qr_code_url", "")
        if qr_code_data_url:
            extras["qr_code"] = f'<img src="{qr_code_data_url}" alt="QR Code" />'
            extras["qr_code_url"] = qr_code_data_url
        elif self.config.enable_qr_code and (link or self.config.qr_link):
            qr_link = link or self.config.qr_link
            qr_data_url = self.qr_generator.generate_data_url(qr_link)
            extras["qr_code"] = f'<img src="{qr_data_url}" alt="QR Code" />'
            extras["qr_code_url"] = qr_data_url

        # Process template
        html = self._template_content

        # Process includes first
        html = self._process_includes(html)

        # Process conditionals
        html = self._process_conditionals(html, data, extras)

        # Process Spintax randomly before placeholders so placeholders inside spintax resolve
        html = self._process_spintax(html)

        # Process placeholders
        html = self.placeholder_processor.process(html, data, extras)

        return html

    def _process_spintax(self, html: str) -> str:
        """Process nested Spintax '{Hi|Hello}' replacement."""
        pattern = re.compile(r"\{([^{}]*\|[^{}]*)\}")

        while True:
            match_count = 0

            def replacer(match):
                nonlocal match_count
                match_count += 1
                options = match.group(1).split("|")
                return random.choice(options)

            html = pattern.sub(replacer, html)
            if match_count == 0:
                break

        return html

    def _process_includes(self, html: str) -> str:
        """
        Process template includes.

        Syntax: {{include:path/to/file.html}}
        """
        pattern = r"\{\{include:([^}]+)\}\}"

        def replace_include(match):
            include_path = match.group(1).strip()

            # Resolve relative to template directory
            if self.config.template_path:
                base_dir = os.path.dirname(self.config.template_path)
                full_path = os.path.join(base_dir, include_path)
            else:
                full_path = include_path

            # Prevent Arbitrary File Read (C-2)
            try:
                target_path = os.path.realpath(full_path)
                safe_base = os.path.realpath(os.getcwd())

                # Further restrict if base_dir is known to be safer than CWD
                if self.config.template_path:
                    safe_base = os.path.realpath(os.path.dirname(self.config.template_path))

                if target_path.startswith(safe_base) and os.path.exists(target_path):
                    with open(target_path, "r", encoding="utf-8") as f:
                        return f.read()
            except Exception as e:
                logger.warning(f"Failed to include {include_path}: {e}")

            return match.group(0)

        return re.sub(pattern, replace_include, html)

    def _process_conditionals(
        self, html: str, recipient_data: Dict[str, Any], extra_placeholders: Dict[str, str]
    ) -> str:
        """
        Process conditional blocks.

        Syntax:
        {{if:placeholder}}content{{endif}}
        {{if:placeholder}}content{{else}}alt_content{{endif}}

        Nesting strategy: match only innermost conditionals (those whose
        body contains no further ``{{if:`` opener) and iterate. This
        avoids the previous bug where a non-greedy ``.*?`` would pair an
        outer ``{{if:}}`` with the *inner* ``{{endif}}``, mangling the
        structure on the very first pass.
        """
        # Combine all placeholder values
        all_values: Dict[str, Any] = {}
        all_values.update(self.placeholder_processor.get_builtin_placeholders(recipient_data))
        all_values.update(self._static_placeholders)
        all_values.update(extra_placeholders)

        # The negative lookahead `(?:(?!\{\{if:).)*?` forbids any nested
        # {{if:}} opener inside the matched body, so only innermost
        # blocks match. Outer blocks become innermost after their nested
        # contents are resolved, then match on the next iteration.
        pattern = re.compile(
            r"\{\{if:([^}]+)\}\}"
            r"((?:(?!\{\{if:).)*?)"
            r"(?:\{\{else\}\}((?:(?!\{\{if:).)*?))?"
            r"\{\{endif\}\}",
            re.DOTALL,
        )

        def _truthy(value: Any) -> bool:
            if value is None:
                return False
            s = str(value).strip().lower()
            if not s:
                return False
            return s not in ("false", "0", "no", "none", "null")

        def replace_conditional(match: re.Match) -> str:
            condition = match.group(1).strip()
            if_content = match.group(2)
            else_content = match.group(3) or ""
            return if_content if _truthy(all_values.get(condition, "")) else else_content

        # Bound the loop to avoid worst-case pathological templates.
        for _ in range(32):
            new_html = pattern.sub(replace_conditional, html)
            if new_html == html:
                break
            html = new_html
        else:
            logger.warning(
                "Conditional resolution didn't converge after 32 passes; possible unbalanced {{if/endif}}"
            )

        return html

    def validate(self) -> Dict[str, Any]:
        """
        Validate template and return analysis.

        Returns:
            Dict with validation results
        """
        if not self._template_content:
            return {"valid": False, "error": "No template content loaded", "placeholders": []}

        result = self.placeholder_processor.validate_placeholders(self._template_content)
        result["template_path"] = self.config.template_path
        result["template_size"] = len(self._template_content)

        return result

    def get_used_placeholders(self) -> List[str]:
        """Get list of placeholders used in template."""
        if not self._template_content:
            return []
        return self.placeholder_processor.get_used_placeholders(self._template_content)

    def preview(
        self,
        recipient: str = "test@example.com",
        extra_placeholders: Optional[Dict[str, str]] = None,
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
            link="https://example.com/preview",
        )


def load_template(template_path: str) -> str:
    """Load template from file."""
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load template {template_path}: {e}")
        return ""
