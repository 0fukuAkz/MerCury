"""Build the placeholder-extras dicts for body and headers.

Two flavors:

* **body_extras** carry the full HTML payload for ``{{qr_code}}`` /
  ``{{company_logo}}`` (an ``<img>`` tag).
* **header_extras** carry the URL forms only. Email headers (Subject, From,
  Reply-To) are plaintext — embedding an ``<img>`` tag would surface the
  literal markup in the inbox.

Both flavors share ``link``/``url`` so ``{{link}}`` resolves consistently in
body AND subject. Earlier code only gave the body access to ``{{link}}``,
which meant ``{{link}}`` in a Subject silently leaked through as literal
template text.
"""
from typing import Dict, Optional, Tuple

from ...features.generators import GeneratorConfig, QRCodeGenerator
from .branding import BrandingResult
from .context import SendContext


def generate_qr_data_url(ctx: SendContext) -> Optional[str]:
    if ctx.config.enable_qr_code and ctx.link:
        return QRCodeGenerator(GeneratorConfig()).generate_data_url(ctx.link)
    return None


def build_extras(
    ctx: SendContext,
    qr_data_url: Optional[str],
    branding: BrandingResult,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Returns ``(body_extras, header_extras)``."""
    body_extras: Dict[str, str] = {
        "link": ctx.link or "",
        "url": ctx.link or "",
        "qr_code": f'<img src="{qr_data_url}" alt="QR Code" />' if qr_data_url else "",
        "qr_code_url": qr_data_url or "",
        "company_logo": branding.logo_img_tag,
        "company_logo_url": branding.logo_data_url,
        "brand": branding.body_brand,
    }
    header_extras: Dict[str, str] = {
        "link": ctx.link or "",
        "url": ctx.link or "",
        # Empty for headers — operators should never see <img> tags in
        # their subject lines or From names.
        "qr_code": "",
        "qr_code_url": "",
        "company_logo": "",
        "company_logo_url": "",
        "brand": branding.header_brand,
    }
    return body_extras, header_extras
