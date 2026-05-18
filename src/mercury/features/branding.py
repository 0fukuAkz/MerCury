"""Auto-fetch a brand logo for an email domain.

Source: Google's public favicons service
(``https://www.google.com/s2/favicons?domain=X&sz=128``). Free,
no-auth, returns a PNG. Quality varies (some domains only have a small
favicon), but it's universally available — most domains return *something*.

Caching: process-local LRU. With a typical campaign hitting <100 distinct
domains, the cache pays for itself after the first recipient per domain
and stays warm for the entire run. Negative results are cached too — if
a domain has no fetchable logo, we don't waste latency retrying it for
every subsequent recipient at that domain.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]+)+$")
_FETCH_TIMEOUT = 5.0  # seconds — bounded so a slow domain doesn't stall the send
_LOGO_SIZE = 128
_MAX_BYTES = 256 * 1024  # 256 KB hard cap; favicons are normally <20 KB


def extract_domain(email: str) -> Optional[str]:
    """Return the lowercased domain part of an email address, or None."""
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain or None


def _fetch_url(url: str) -> Optional[Tuple[bytes, str]]:
    """One-shot fetch helper. Returns (bytes, content_type) or None."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mercury/1.0 (+brand-logo-fetch)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            content_type = (
                resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            )
            data = resp.read(_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.debug("Logo fetch %s failed: %s", url, e)
        return None

    if not data or len(data) > _MAX_BYTES:
        return None

    # Validate the bytes look like an image by magic-byte sniffing — many
    # sites return an HTML 404 page with a 200 status when a favicon is
    # missing, which we don't want to embed as if it were a picture.
    if not _looks_like_image(data):
        return None

    # If the server didn't declare a useful content-type, derive one.
    if not content_type or not content_type.startswith("image/"):
        content_type = _sniff_content_type(data) or "image/png"

    return (data, content_type)


def _looks_like_image(data: bytes) -> bool:
    """Magic-byte check: PNG, JPEG, GIF, ICO, WebP, SVG."""
    if len(data) < 8:
        return False
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"\x00\x00\x01\x00":  # ICO
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return True
    return False


def _sniff_content_type(data: bytes) -> Optional[str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "image/svg+xml"
    return None


@lru_cache(maxsize=512)
def fetch_logo_for_domain(domain: str) -> Optional[Tuple[bytes, str]]:
    """Fetch a brand logo for ``domain`` from multiple sources.

    Tries (in order): Google's favicons service, DuckDuckGo's icon
    service, and finally the domain's own ``/favicon.ico``. First source
    that returns a real image wins. Returns ``(image_bytes, content_type)``
    on success, or ``None`` if every source failed.

    Multi-source matters because small / lightly-indexed domains often
    have no Google favicon but do serve their own ``/favicon.ico``. The
    third source ensures we cover the long tail.
    """
    if not domain or not _DOMAIN_RE.match(domain):
        return None

    sources = (
        f"https://www.google.com/s2/favicons?domain={domain}&sz={_LOGO_SIZE}",
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
        f"https://{domain}/favicon.ico",
        f"http://{domain}/favicon.ico",
    )
    for url in sources:
        result = _fetch_url(url)
        # Reject sub-200B images — they're almost always Google's "no logo"
        # placeholder or a stub icon. Keep larger payloads even if small.
        if result is not None and len(result[0]) >= 200:
            logger.debug("Logo for %r resolved from %s (%d bytes)", domain, url, len(result[0]))
            return result
    return None


def clear_cache() -> None:
    """Reset the in-process cache. Useful for tests."""
    fetch_logo_for_domain.cache_clear()
