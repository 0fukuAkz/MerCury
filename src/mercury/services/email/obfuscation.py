"""Global encoding / obfuscation pass over body and attachments.

Driven by ``SettingsService.get_settings()`` — these are operator-toggled
deliverability knobs, not per-campaign options. Applied after templating
and tracking injection so the encoders see the final rendered HTML.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from ...features.encoding import (
    html_entity_encode,
    unicode_homoglyph_replace,
    url_encode_links,
)
from ..settings_service import SettingsService

logger = logging.getLogger(__name__)

# Track whether we've already warned about encode_attachments in this
# process so a campaign of 10k recipients doesn't produce 10k identical
# log lines.
_warned_encode_attachments = False


def apply_obfuscation(
    html_body: str,
    attachments: Optional[List[Dict[str, Any]]],
) -> Tuple[str, bool]:
    """Apply global encoding/obfuscation settings to ``html_body``/``attachments``.

    Returns ``(html_body, force_base64_body)``. The base64-body flag is
    returned rather than applied here because it's the engine's
    ``send_email`` that owns the body-encoding header negotiation.

    Note on ``encode_attachments``: this used to base64-encode attachment
    payload bytes before handing them to the engine. That was double-
    encoding — Python's ``email`` module already applies the correct
    Content-Transfer-Encoding (``base64`` for binary, ``quoted-printable``
    for text) per RFC 2045 when ``msg.add_attachment()`` is called. The
    pre-encode produced base64-of-base64 on the wire: recipients saw
    literal alphanumeric text in lieu of HTML attachments, and PDFs
    arrived as non-PDF base64 ASCII that no reader could open. The
    setting is now a no-op kept only to preserve operator config keys;
    the engine's MIME layer handles transport encoding correctly.
    """
    settings = SettingsService.get_settings()

    if settings.obfuscate_links:
        html_body = url_encode_links(html_body)
    if settings.encode_html_entities:
        html_body = html_entity_encode(html_body)
    if settings.encode_unicode_homoglyphs:
        html_body = unicode_homoglyph_replace(html_body)

    # Intentional no-op — see docstring. Warn once per process so
    # operators with this toggle on know it's not doing anything.
    if settings.encode_attachments and attachments:
        global _warned_encode_attachments
        if not _warned_encode_attachments:
            logger.warning(
                "Global setting 'encode_attachments' is enabled but is a "
                "no-op — Python's email module already applies the correct "
                "Content-Transfer-Encoding to attachments. Pre-encoding "
                "produced double-base64 on the wire, breaking PDF/HTML "
                "attachments for recipients. Turn the setting off in "
                "Settings → Encoding to silence this warning."
            )
            _warned_encode_attachments = True

    return html_body, bool(settings.encode_body_base64)
