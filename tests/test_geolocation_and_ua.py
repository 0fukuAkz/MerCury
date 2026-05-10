"""Tests for geolocation + user-agent placeholder enrichment.

Covers:
- UA parser shape + a few representative real-world strings.
- GeoResolver fail-open semantics (no DB, no geoip2, missing file).
- Placeholder integration: {{location.country}} and {{ua.browser}} resolve
  end-to-end through the processor when recipient_data carries ip/ua.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from mercury.features.user_agent import parse as parse_ua
from mercury.features.geolocation import GeoResolver, get_resolver, reset_resolver_for_tests
from mercury.features.placeholders import PlaceholderProcessor


# ───── UA parser ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("ua,expected", [
    (
        # Chrome 122 on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        {"browser": "Chrome", "os": "macOS", "device": "Desktop"},
    ),
    (
        # Safari iPhone iOS 17
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        {"browser": "Safari", "os": "iOS", "device": "Mobile"},
    ),
    (
        # Firefox on Windows 10
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        {"browser": "Firefox", "os": "Windows", "os_version": "10", "device": "Desktop"},
    ),
    (
        # Edge on Windows 11 (still NT 10.0)
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        {"browser": "Edge", "os": "Windows", "device": "Desktop"},
    ),
    (
        # Generic crawler — should be classified as Bot regardless of browser
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        {"device": "Bot"},
    ),
])
def test_parse_ua_real_world(ua, expected):
    out = parse_ua(ua)
    for k, v in expected.items():
        assert out[k] == v, f"key={k!r} expected {v!r} got {out[k]!r} (full: {out})"


def test_parse_ua_empty_returns_full_shape():
    out = parse_ua(None)
    # Same key set whether parse succeeds or not — placeholder lookups depend on it.
    assert set(out.keys()) >= {"browser", "browser_version", "os", "os_version", "device", "raw"}
    assert all(out[k] == "" for k in ("browser", "os", "device"))


def test_parse_ua_ios_version_normalized():
    """iOS uses 17_0 in UA strings; templates should see 17.0."""
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605"
    assert parse_ua(ua)["os_version"] == "17.2"


# ───── GeoResolver fail-open paths ────────────────────────────────────────

def test_geo_resolver_no_db_path_returns_empty(monkeypatch):
    """No MERCURY_GEOIP_DB set → resolver disabled, all keys empty."""
    monkeypatch.delenv("MERCURY_GEOIP_DB", raising=False)
    r = GeoResolver()
    out = r.resolve("8.8.8.8")
    assert out["country"] == "" and out["city"] == ""
    # Full key shape preserved
    assert set(out.keys()) >= {"country", "country_code", "city", "region", "timezone"}


def test_geo_resolver_missing_db_file(tmp_path, monkeypatch):
    """Path set but file doesn't exist → disabled, no crash."""
    monkeypatch.setenv("MERCURY_GEOIP_DB", str(tmp_path / "nope.mmdb"))
    r = GeoResolver()
    assert r.resolve("8.8.8.8")["country"] == ""


def test_geo_resolver_private_ip_skips_lookup():
    """RFC1918 / loopback addresses short-circuit to empty without invoking the reader."""
    r = GeoResolver()
    r._available = True  # pretend reader is loaded
    r._reader = MagicMock()  # would raise if called
    assert r.resolve("127.0.0.1") == {k: "" for k in r.resolve("127.0.0.1")}
    assert r.resolve("192.168.1.5")["country"] == ""
    assert r.resolve("10.0.0.1")["country"] == ""
    assert r.resolve("172.20.0.5")["country"] == ""  # in-range
    r._reader.city.assert_not_called()


def test_geo_resolver_172_boundary_public_still_queries():
    """172.32.x is public IP space — must NOT short-circuit."""
    r = GeoResolver()
    r._available = True
    r._reader = MagicMock()
    r._reader.city.side_effect = Exception("boom")  # forces empty, but proves call happened
    r.resolve("172.32.1.1")
    r._reader.city.assert_called_once()


def test_geo_resolver_handles_geoip2_exceptions(monkeypatch):
    """A reader exception (AddressNotFoundError, ValueError) maps to empty dict."""
    r = GeoResolver()
    r._available = True
    r._reader = MagicMock()
    r._reader.city.side_effect = Exception("AddressNotFound")
    out = r.resolve("8.8.8.8")
    assert out["country"] == ""


def test_get_resolver_singleton(monkeypatch):
    monkeypatch.delenv("MERCURY_GEOIP_DB", raising=False)
    reset_resolver_for_tests()
    a = get_resolver()
    b = get_resolver()
    assert a is b
    reset_resolver_for_tests()


# ───── Placeholder integration ────────────────────────────────────────────

def test_placeholder_ua_keys_populated_from_recipient_data():
    proc = PlaceholderProcessor()
    out = proc.process(
        "{{ua.browser}} on {{ua.os}} ({{ua.device}})",
        recipient_data={
            "email": "x@y.com",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
                          "Gecko/20100101 Firefox/121.0",
        },
    )
    assert out == "Firefox on Windows (Desktop)"


def test_placeholder_ua_keys_empty_without_recipient_ua():
    """No `user_agent` on recipient → ua.* placeholders stay empty (template renders blank)."""
    proc = PlaceholderProcessor()
    out = proc.process("[{{ua.browser}}]", recipient_data={"email": "x@y.com"})
    assert out == "[]"


def test_placeholder_geo_keys_resolved_when_resolver_returns_data():
    """Stub the resolver so we don't need a real .mmdb in CI."""
    fake_geo = {
        "country": "United States", "country_code": "US",
        "city": "Mountain View", "region": "California", "region_code": "CA",
        "timezone": "America/Los_Angeles", "continent": "North America", "postal": "94043",
    }
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        gr.return_value.resolve.return_value = fake_geo
        proc = PlaceholderProcessor()
        out = proc.process(
            "Hi from {{location.city}}, {{location.country_code}}",
            recipient_data={"email": "x@y.com", "ip": "8.8.8.8"},
        )
    assert out == "Hi from Mountain View, US"


def test_placeholder_geo_keys_empty_without_ip():
    """Missing IP → resolver isn't called and all location.* keys stay blank."""
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        proc = PlaceholderProcessor()
        out = proc.process("[{{location.country}}]", recipient_data={"email": "x@y.com"})
        gr.assert_not_called()
    assert out == "[]"


def test_placeholder_top_level_location_full():
    """{{location}} composes 'City, Region, Country' when all are known."""
    fake_geo = {
        "country": "United States", "country_code": "US",
        "city": "Mountain View", "region": "California", "region_code": "CA",
        "timezone": "", "continent": "", "postal": "",
    }
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        gr.return_value.resolve.return_value = fake_geo
        proc = PlaceholderProcessor()
        out = proc.process(
            "Greetings from {{location}}!",
            recipient_data={"email": "x@y.com", "ip": "8.8.8.8"},
        )
    assert out == "Greetings from Mountain View, California, United States!"


def test_placeholder_top_level_location_no_region():
    """City + Country without region renders as 'City, Country'."""
    fake_geo = {"country": "Germany", "country_code": "DE", "city": "Berlin",
                "region": "", "region_code": "", "timezone": "", "continent": "", "postal": ""}
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        gr.return_value.resolve.return_value = fake_geo
        proc = PlaceholderProcessor()
        out = proc.process("[{{location}}]", recipient_data={"email": "x@y.com", "ip": "1.1.1.1"})
    assert out == "[Berlin, Germany]"


def test_placeholder_top_level_location_country_only():
    """Country-only resolution still produces a non-empty render."""
    fake_geo = {"country": "Japan", "country_code": "JP", "city": "",
                "region": "", "region_code": "", "timezone": "", "continent": "", "postal": ""}
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        gr.return_value.resolve.return_value = fake_geo
        proc = PlaceholderProcessor()
        out = proc.process("[{{location}}]", recipient_data={"email": "x@y.com", "ip": "1.1.1.1"})
    assert out == "[Japan]"


def test_placeholder_top_level_location_empty_when_no_ip():
    """No IP → no resolver call → {{location}} renders blank."""
    proc = PlaceholderProcessor()
    out = proc.process("[{{location}}]", recipient_data={"email": "x@y.com"})
    assert out == "[]"


def test_placeholder_top_level_location_dedupes_city_eq_region():
    """City and region with the same name (e.g. New York City + New York
    state) shouldn't render twice."""
    fake_geo = {"country": "United States", "country_code": "US",
                "city": "New York", "region": "New York", "region_code": "NY",
                "timezone": "", "continent": "", "postal": ""}
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        gr.return_value.resolve.return_value = fake_geo
        proc = PlaceholderProcessor()
        out = proc.process("[{{location}}]", recipient_data={"email": "x@y.com", "ip": "1.1.1.1"})
    assert out == "[New York, United States]"


def test_placeholder_top_level_ua_full():
    """{{ua}} composes 'Browser on OS' when both are known."""
    proc = PlaceholderProcessor()
    out = proc.process(
        "Sent to {{ua}}",
        recipient_data={
            "email": "x@y.com",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0) Gecko/20100101 Firefox/121.0",
        },
    )
    assert out == "Sent to Firefox on Windows"


def test_placeholder_top_level_ua_browser_only():
    """OS-less UA falls back to browser name alone."""
    # A bot UA: classified as Bot device, no OS pattern matches.
    proc = PlaceholderProcessor()
    out = proc.process(
        "[{{ua}}]",
        recipient_data={
            "email": "x@y.com",
            "user_agent": "curl/8.0.1",
        },
    )
    # curl matches the bot hint; no browser pattern, no OS pattern → empty.
    # Use a real browser+empty-OS combination instead:
    out2 = proc.process(
        "[{{ua}}]",
        recipient_data={
            "email": "x@y.com",
            "user_agent": "Chrome/122.0.0.0",  # bare browser, no OS bracket
        },
    )
    assert out2 == "[Chrome]"


def test_placeholder_top_level_ua_empty_without_input():
    proc = PlaceholderProcessor()
    out = proc.process("[{{ua}}]", recipient_data={"email": "x@y.com"})
    assert out == "[]"


def test_placeholder_alt_keys_ip_address_and_ua():
    """Recipient rows can also use ``ip_address`` / ``ua`` as column names."""
    fake_geo = {"country": "Germany", "country_code": "DE", "city": "Berlin",
                "region": "", "region_code": "", "timezone": "", "continent": "", "postal": ""}
    with patch("mercury.features.placeholders._get_geo_resolver") as gr:
        gr.return_value.resolve.return_value = fake_geo
        proc = PlaceholderProcessor()
        out = proc.process(
            "{{location.country}} / {{ua.browser}}",
            recipient_data={
                "email": "x@y.com",
                "ip_address": "8.8.8.8",
                "ua": "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/120.0",
            },
        )
    assert out == "Germany / Firefox"
