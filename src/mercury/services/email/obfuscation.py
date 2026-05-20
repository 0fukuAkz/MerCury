"""Global encoding / obfuscation pass over body and attachments.

Driven by ``SettingsService.get_settings()`` — these are operator-toggled
deliverability knobs, not per-campaign options. Applied after templating
and tracking injection so the encoders see the final rendered HTML.
"""
from typing import Any, Dict, List, Optional, Tuple

from ...features.encoding import (
    base64_encode_attachment,
    html_entity_encode,
    unicode_homoglyph_replace,
    url_encode_links,
)
from ..settings_service import SettingsService


def apply_obfuscation(
    html_body: str,
    attachments: Optional[List[Dict[str, Any]]],
) -> Tuple[str, bool]:
    """Apply global encoding/obfuscation settings to ``html_body``/``attachments``.

    Returns ``(html_body, force_base64_body)``. The base64-body flag is
    returned rather than applied here because it's the engine's
    ``send_email`` that owns the body-encoding header negotiation.
    """
    settings = SettingsService.get_settings()

    if settings.obfuscate_links:
        html_body = url_encode_links(html_body)
    if settings.encode_html_entities:
        html_body = html_entity_encode(html_body)
    if settings.encode_unicode_homoglyphs:
        html_body = unicode_homoglyph_replace(html_body)
    if settings.encode_attachments and attachments:
        for att in attachments:
            att['data'] = base64_encode_attachment(att['data'])

    return html_body, bool(settings.encode_body_base64)
