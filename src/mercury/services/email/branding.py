"""Brand logo + ``{{brand}}`` resolution.

Resolution order:

1. Pinned attachment-library logo (``config.logo_attachment_id``) — operator
   uploaded a logo via the Attachments library and pinned it to the campaign.
2. Auto-fetch from the recipient's email domain (when
   ``config.auto_company_logo`` is on) — per-recipient personalization for
   free.
3. Fall back to the domain name rendered as styled text — so operators can
   write ``{{brand}}`` once and have *something* render every time.

The logo is *never* sent as an attachment — it's inlined as a ``data:`` URL
into ``{{company_logo}}`` / ``{{company_logo_url}}``.
"""
import base64
import logging
from dataclasses import dataclass

from .context import SendContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrandingResult:
    logo_img_tag: str
    logo_data_url: str
    company_text: str
    body_brand: str
    header_brand: str


def resolve_branding(ctx: SendContext) -> BrandingResult:
    logo_img_tag = ""
    logo_data_url = ""

    if ctx.config.logo_attachment_id:
        logo_img_tag, logo_data_url = _load_pinned_logo(ctx.config.logo_attachment_id)

    if not logo_img_tag and ctx.config.auto_company_logo:
        logo_img_tag, logo_data_url = _auto_fetch_logo(ctx.recipient)

    company_text = _derive_company_text(ctx.recipient)

    body_brand = (
        logo_img_tag
        if logo_img_tag
        else (f'<span class="company-name">{company_text}</span>' if company_text else "")
    )

    return BrandingResult(
        logo_img_tag=logo_img_tag,
        logo_data_url=logo_data_url,
        company_text=company_text,
        body_brand=body_brand,
        header_brand=company_text,
    )


def _load_pinned_logo(logo_id: int) -> tuple[str, str]:
    """Returns ``(img_tag, data_url)`` or ``('', '')`` on any failure (logged)."""
    try:
        from ...data.database import session_scope
        from ...data.repositories import AttachmentRepository
        from ...utils.app_dirs import get_data_dir

        with session_scope() as session:
            row = AttachmentRepository(session).get(int(logo_id))
            if row is None or not row.is_active:
                logger.warning(
                    f"[logo] id={logo_id} missing/inactive in DB; " "{{company_logo}} renders empty"
                )
                return "", ""
            disk = get_data_dir() / "attachments" / row.stored_name
            if not disk.is_file():
                logger.error(f"[logo] id={logo_id} ({row.filename}) missing on disk at {disk}")
                return "", ""
            if not (row.content_type or "").lower().startswith("image/"):
                # Defensive: refuse to inline a non-image as if it were one.
                # Some clients render data:text/html;base64,... as inline
                # content, which leaks the file's source into the email.
                logger.warning(
                    f"[logo] id={logo_id} ({row.filename}) is not an image "
                    f"(content_type={row.content_type!r}); "
                    "{{company_logo}} renders empty"
                )
                return "", ""
            blob = disk.read_bytes()
            b64 = base64.b64encode(blob).decode("ascii")
            data_url = f"data:{row.content_type};base64,{b64}"
            return f'<img src="{data_url}" alt="Logo" />', data_url
    except Exception as e:
        logger.error(f"[logo] failed to inline company_logo: {e}")
        return "", ""


def _auto_fetch_logo(recipient: str) -> tuple[str, str]:
    """Auto-fetch from the recipient's email domain.

    Returns ``('', '')`` if the domain can't be extracted, no logo is found,
    or any error occurs (logged at info/warning).
    """
    try:
        from ...features.branding import (
            extract_domain,
            fetch_logo_for_domain,
        )

        dom = extract_domain(recipient)
        if not dom:
            return "", ""
        fetched = fetch_logo_for_domain(dom)
        if fetched is None:
            logger.info(f"[logo] auto-fetch: no logo found for domain={dom!r}")
            return "", ""
        blob, ct = fetched
        b64 = base64.b64encode(blob).decode("ascii")
        data_url = f"data:{ct};base64,{b64}"
        return f'<img src="{data_url}" alt="Logo" />', data_url
    except Exception as e:
        logger.warning(f"[logo] auto-fetch failed for recipient={recipient!r}: {e}")
        return "", ""


def _derive_company_text(recipient: str) -> str:
    if not (recipient and "@" in recipient):
        return ""
    dom = recipient.rsplit("@", 1)[1]
    dom_name = dom.split(".", 1)[0] if dom else ""
    return dom_name.capitalize() if dom_name else ""
