"""Encoding and obfuscation utilities for email content."""

import base64
import re
from html.parser import HTMLParser
from urllib.parse import quote as url_quote


# ── Homoglyph map: ASCII → visually identical Unicode ──────────────────
_HOMOGLYPHS = {
    "a": "\u0430",  # Cyrillic а
    "c": "\u0441",  # Cyrillic с
    "d": "\u0501",  # Cyrillic ԁ
    "e": "\u0435",  # Cyrillic е
    "h": "\u04BB",  # Cyrillic һ
    "i": "\u0456",  # Cyrillic і
    "j": "\u0458",  # Cyrillic ј
    "o": "\u043E",  # Cyrillic о
    "p": "\u0440",  # Cyrillic р
    "s": "\u0455",  # Cyrillic ѕ
    "x": "\u0445",  # Cyrillic х
    "y": "\u0443",  # Cyrillic у
    "A": "\u0410",  # Cyrillic А
    "B": "\u0412",  # Cyrillic В
    "C": "\u0421",  # Cyrillic С
    "E": "\u0415",  # Cyrillic Е
    "H": "\u041D",  # Cyrillic Н
    "K": "\u041A",  # Cyrillic К
    "M": "\u041C",  # Cyrillic М
    "O": "\u041E",  # Cyrillic О
    "P": "\u0420",  # Cyrillic Р
    "T": "\u0422",  # Cyrillic Т
    "X": "\u0425",  # Cyrillic Х
}


class _TextNodeExtractor(HTMLParser):
    """Parse HTML and rebuild it, applying a transform function to text nodes only."""

    def __init__(self, transform_fn):
        super().__init__(convert_charrefs=False)
        self._transform = transform_fn
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr_str = ""
        for k, v in attrs:
            if v is None:
                attr_str += f" {k}"
            else:
                attr_str += f' {k}="{v}"'
        self._parts.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        self._parts.append(f"</{tag}>")

    def handle_data(self, data):
        self._parts.append(self._transform(data))

    def handle_entityref(self, name):
        self._parts.append(f"&{name};")

    def handle_charref(self, name):
        self._parts.append(f"&#{name};")

    def handle_comment(self, data):
        self._parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self._parts.append(f"<!{decl}>")

    def handle_pi(self, data):
        self._parts.append(f"<?{data}>")

    def get_result(self) -> str:
        return "".join(self._parts)


def _transform_text_nodes(html: str, transform_fn) -> str:
    """Apply transform_fn to every text node in HTML, preserving tags."""
    parser = _TextNodeExtractor(transform_fn)
    parser.feed(html)
    return parser.get_result()


# ── Public API ──────────────────────────────────────────────────────────


def base64_encode_attachment(data: bytes) -> bytes:
    """Base64-encode raw attachment bytes."""
    return base64.b64encode(data)


def html_entity_encode(html: str) -> str:
    """Convert characters in text nodes to HTML numeric entities."""

    def _encode_text(text: str) -> str:
        return "".join(f"&#{ord(c)};" if c not in ("\n", "\r", "\t", " ") else c for c in text)

    return _transform_text_nodes(html, _encode_text)


def unicode_homoglyph_replace(html: str) -> str:
    """Replace select ASCII characters in text nodes with Unicode homoglyphs."""

    def _replace_text(text: str) -> str:
        return "".join(_HOMOGLYPHS.get(c, c) for c in text)

    return _transform_text_nodes(html, _replace_text)


def url_encode_links(html: str) -> str:
    """Percent-encode characters in href URL values."""

    def _encode_href(match):
        quote_char = match.group(1)
        url = match.group(2)
        # Encode the URL but preserve the scheme separator and path structure
        # Split on :// to keep the scheme readable
        if "://" in url:
            scheme, rest = url.split("://", 1)
            encoded = scheme + "://" + url_quote(rest, safe="/:@!$&'()*+,;=-._~?#[]%")
        else:
            encoded = url_quote(url, safe="/:@!$&'()*+,;=-._~?#[]%")
        return f"href={quote_char}{encoded}{quote_char}"

    return re.sub(r'href=(["\'])(.*?)\1', _encode_href, html)
