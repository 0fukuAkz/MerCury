"""Tests for email logo fetching features (branding)."""

import urllib.error
from unittest.mock import MagicMock, patch

from mercury.features.branding import (
    extract_domain,
    _looks_like_image,
    _sniff_content_type,
    _fetch_url,
    fetch_logo_for_domain,
    clear_cache,
)


class TestBrandingFeatures:
    """Test logo fetching and branding utilities."""

    def test_extract_domain(self):
        """Test extract_domain with various inputs."""
        assert extract_domain("user@example.com") == "example.com"
        assert extract_domain("user@Sub.Example.Com") == "sub.example.com"
        assert extract_domain("") is None
        assert extract_domain("no-at-symbol") is None
        assert extract_domain("@no-local-part.com") == "no-local-part.com"

    def test_looks_like_image(self):
        """Test magic-byte checking for image types."""
        # Short data
        assert _looks_like_image(b"abc") is False

        # PNG
        assert _looks_like_image(b"\x89PNG\r\n\x1a\n") is True
        assert _looks_like_image(b"\x89PNG\r\n\x1a\nExtraBytes") is True

        # JPEG
        assert _looks_like_image(b"\xff\xd8\xff\x00\x00\x00\x00\x00") is True
        assert _looks_like_image(b"\xff\xd8\xff\x00\x00\x00\x00\x00ExtraBytes") is True

        # GIF
        assert _looks_like_image(b"GIF87a\x00\x00") is True
        assert _looks_like_image(b"GIF89a\x00\x00") is True

        # ICO
        assert _looks_like_image(b"\x00\x00\x01\x00\x00\x00\x00\x00") is True

        # WebP
        assert _looks_like_image(b"RIFF\x00\x00\x00\x00WEBP") is True
        assert _looks_like_image(b"RIFF\x12\x34\x56\x78WEBP") is True
        assert _looks_like_image(b"RIFF\x12\x34\x56\x78WEBA") is False

        # SVG / XML
        assert _looks_like_image(b"<svg xmlns='http://www.w3.org/2000/svg'>") is True
        assert _looks_like_image(b"<?xml version='1.0'?><svg>") is True
        assert _looks_like_image(b"   \t\n  <svg>") is True
        assert _looks_like_image(b"not-svg\x00\x00") is False

    def test_sniff_content_type(self):
        """Test sniffing of mime-types using magic bytes."""
        assert _sniff_content_type(b"\x89PNG\r\n\x1a\n") == "image/png"
        assert _sniff_content_type(b"\xff\xd8\xff") == "image/jpeg"
        assert _sniff_content_type(b"GIF87a") == "image/gif"
        assert _sniff_content_type(b"\x00\x00\x01\x00") == "image/x-icon"
        assert _sniff_content_type(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"
        assert _sniff_content_type(b"<svg>") == "image/svg+xml"
        assert _sniff_content_type(b"unknown data") is None

    @patch("urllib.request.urlopen")
    def test_fetch_url_success(self, mock_urlopen):
        """Test _fetch_url with a successful response containing an image."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.read.return_value = b"\x89PNG\r\n\x1a\nImageBytes"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = _fetch_url("http://example.com/logo.png")
        assert result is not None
        data, content_type = result
        assert data == b"\x89PNG\r\n\x1a\nImageBytes"
        assert content_type == "image/png"

    @patch("urllib.request.urlopen")
    def test_fetch_url_without_status_attribute(self, mock_urlopen):
        """Test _fetch_url where response has no status attribute (assumes 200)."""
        mock_resp = MagicMock()
        del mock_resp.status
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.read.return_value = b"\x89PNG\r\n\x1a\nImageBytes"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = _fetch_url("http://example.com/logo.png")
        assert result is not None
        assert result[1] == "image/png"

    @patch("urllib.request.urlopen")
    def test_fetch_url_non_200_status(self, mock_urlopen):
        """Test _fetch_url returning non-200 status."""
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        assert _fetch_url("http://example.com/logo.png") is None

    @patch("urllib.request.urlopen")
    def test_fetch_url_oversized(self, mock_urlopen):
        """Test _fetch_url returning too much data."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        # max size is 256 KB = 262144 bytes, so return more than that plus 1
        mock_resp.read.return_value = b"\x89PNG\r\n\x1a\n" + (b"A" * 262145)
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        assert _fetch_url("http://example.com/logo.png") is None

    @patch("urllib.request.urlopen")
    def test_fetch_url_empty_data(self, mock_urlopen):
        """Test _fetch_url returning empty data."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.read.return_value = b""
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        assert _fetch_url("http://example.com/logo.png") is None

    @patch("urllib.request.urlopen")
    def test_fetch_url_not_image(self, mock_urlopen):
        """Test _fetch_url returning data that represents HTML/text instead of an image."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.read.return_value = b"<html><body>Not a logo</body></html>"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        assert _fetch_url("http://example.com/logo.png") is None

    @patch("urllib.request.urlopen")
    def test_fetch_url_unrecognized_content_type_sniff(self, mock_urlopen):
        """Test _fetch_url sniffing content-type when return headers are empty or non-image."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.read.return_value = b"\x89PNG\r\n\x1a\n"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = _fetch_url("http://example.com/logo.png")
        assert result is not None
        assert result[1] == "image/png"

    @patch("urllib.request.urlopen")
    def test_fetch_url_exceptions(self, mock_urlopen):
        """Test that _fetch_url handles various urllib network/protocol errors gracefully."""
        mock_urlopen.side_effect = urllib.error.URLError("URLError test")
        assert _fetch_url("http://example.com/logo.png") is None

        mock_urlopen.side_effect = OSError("OSError test")
        assert _fetch_url("http://example.com/logo.png") is None

        mock_urlopen.side_effect = ValueError("ValueError test")
        assert _fetch_url("http://example.com/logo.png") is None

    @patch("mercury.features.branding._fetch_url")
    def test_fetch_logo_for_domain_invalid(self, mock_fetch_url):
        """Test fetch_logo_for_domain with bad inputs."""
        assert fetch_logo_for_domain("") is None
        assert fetch_logo_for_domain("invalid--domain") is None
        mock_fetch_url.assert_not_called()

    @patch("mercury.features.branding._fetch_url")
    def test_fetch_logo_for_domain_success(self, mock_fetch_url):
        """Test fetch_logo_for_domain successfully returning from Google Favicon service."""
        clear_cache()
        # Mock Google (first source) to succeed with valid logo bytes >= 200 bytes
        logo_data = b"\x89PNG\r\n\x1a\n" + (b"B" * 200)
        mock_fetch_url.return_value = (logo_data, "image/png")

        result = fetch_logo_for_domain("example.com")
        assert result is not None
        assert result[0] == logo_data
        assert result[1] == "image/png"
        assert mock_fetch_url.call_count == 1

    @patch("mercury.features.branding._fetch_url")
    def test_fetch_logo_for_domain_falls_back(self, mock_fetch_url):
        """Test fetch_logo_for_domain falls back to DDG or local favicon when first source fails or is small."""
        clear_cache()
        logo_data = b"\xff\xd8\xff" + (b"A" * 300)

        # Mock results:
        # 1. Google returns small/placeholder (less than 200 bytes)
        # 2. DuckDuckGo returns None
        # 3. https://example.com/favicon.ico succeeds with large logo
        mock_fetch_url.side_effect = [
            (b"\x00\x00\x01\x00123", "image/x-icon"),  # < 200 bytes
            None,
            (logo_data, "image/jpeg"),
        ]

        result = fetch_logo_for_domain("example.com")
        assert result is not None
        assert result[0] == logo_data
        assert result[1] == "image/jpeg"
        assert mock_fetch_url.call_count == 3

    @patch("mercury.features.branding._fetch_url")
    def test_fetch_logo_for_domain_all_fail(self, mock_fetch_url):
        """Test fetch_logo_for_domain returns None when all targets fail."""
        clear_cache()
        mock_fetch_url.return_value = None

        result = fetch_logo_for_domain("example.com")
        assert result is None
        # Should probe all 4 URLs: Google icon, DDG icon, https favicon, http favicon
        assert mock_fetch_url.call_count == 4
