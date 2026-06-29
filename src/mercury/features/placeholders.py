"""Placeholder processor with 50+ built-in placeholders."""

import re
import uuid
import random
import hashlib
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List, Callable
import logging

from .geolocation import get_resolver as _get_geo_resolver
from .user_agent import parse as _parse_user_agent

logger = logging.getLogger(__name__)

# Try to import Faker for realistic data
try:
    from faker import Faker

    fake = Faker()
    HAS_FAKER = True
except ImportError:
    HAS_FAKER = False
    fake = None


def _compose_location(p: Dict[str, str]) -> str:
    """Build the {{location}} default string from the resolved location.* keys.

    Fallback ladder, picking the first non-empty form:
      "City, Region, Country"  → if all three present
      "City, Country"          → if region missing
      "City"                   → if only city
      "Region, Country"        → if no city
      "Country"                → last resort
      ""                       → nothing resolved
    """
    city = p.get("location.city", "") or ""
    region = p.get("location.region", "") or ""
    country = p.get("location.country", "") or ""
    parts: List[str] = []
    if city:
        parts.append(city)
        if region and region.lower() != city.lower():
            parts.append(region)
    elif region:
        parts.append(region)
    if country and country not in parts:
        parts.append(country)
    return ", ".join(parts)


def _compose_ua(p: Dict[str, str]) -> str:
    """Build the {{ua}} default string from the parsed ua.* keys.

    "Browser on OS" reads naturally in templates (e.g. "Chrome on Windows").
    If only one half is known we still want a useful render, so we degrade
    to whichever is present.
    """
    browser = p.get("ua.browser", "") or ""
    os_name = p.get("ua.os", "") or ""
    if browser and os_name:
        return f"{browser} on {os_name}"
    return browser or os_name or ""


class PlaceholderProcessor:
    """
    Process placeholders in templates with 50+ built-in placeholders.

    Placeholder syntax: {{placeholder_name}}

    Categories:
    - Recipient: email, domain, local_part, first_name, last_name, etc.
    - Date/Time: date, time, year, month, day, etc.
    - Random: random_name, random_company, random_phone, uuid, etc.
    - Custom: user-defined placeholders
    """

    def __init__(self, static_placeholders: Optional[Dict[str, str]] = None):
        """
        Initialize placeholder processor.

        Args:
            static_placeholders: Static placeholder values that don't change
        """
        self.static_placeholders = static_placeholders or {}
        self._custom_generators: Dict[str, Callable[[], str]] = {}

        # Cache for expensive computations
        self._cache: Dict[str, str] = {}

    def register_generator(self, name: str, generator: Callable[[], str]):
        """Register a custom placeholder generator."""
        self._custom_generators[name] = generator

    def get_builtin_placeholders(
        self, recipient_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Get all built-in placeholder values.

        Args:
            recipient_data: Recipient-specific data

        Returns:
            Dict of placeholder name -> value
        """
        recipient_data = recipient_data or {}
        now = datetime.now(UTC)

        # Build a case-and-format-tolerant lookup view over recipient_data so
        # CSV columns like "First Name" / "FirstName" / "First_Name" / "fname"
        # all resolve to {{first_name}}. Previously only the exact key
        # "first_name" matched, and any other capitalization silently fell
        # back to the email-local-part derivation — which produced
        # convincing-but-wrong values ("Support" from support@x.com) that
        # operators perceived as "the placeholder doesn't work."
        #
        # We do this only for the well-known built-in fields. Arbitrary CSV
        # columns still match by their literal name (the right contract: a
        # `region` column reaches `{{region}}` literally).
        def _lookup(*candidates: str) -> str:
            """Find the first non-empty value among given key candidates,
            tried both exactly and case-insensitively."""
            # Exact match (fast path; preserves original behavior)
            for k in candidates:
                v = recipient_data.get(k)
                if v not in (None, ""):
                    return str(v)
            # Case-insensitive match across recipient_data keys, with
            # whitespace and punctuation normalized to underscore so
            # "First Name", "First_Name", "first-name" all collapse.
            normalized = {
                re.sub(r"[\s\-]+", "_", k.strip().lower()): v
                for k, v in recipient_data.items()
                if isinstance(k, str)
            }
            for k in candidates:
                v = normalized.get(re.sub(r"[\s\-]+", "_", k.lower()))
                if v not in (None, ""):
                    return str(v)
            return ""

        # Parse email if provided
        email = _lookup("email", "recipient_email", "recipient")
        local_part = ""
        domain = ""
        domain_name = ""
        tld = ""

        if "@" in email:
            local_part, domain = email.rsplit("@", 1)
            if "." in domain:
                domain_name = domain.rsplit(".", 1)[0]
                tld = domain.rsplit(".", 1)[1]
            else:
                domain_name = domain

        # Generate first/last name from email if not provided.
        # Tolerant lookup means a CSV with any reasonable spelling of the
        # name columns (First Name, FirstName, first_name, fname, etc.)
        # wins over the email-derived fallback.
        first_name = _lookup("first_name", "firstname", "first", "fname", "given_name")
        last_name = _lookup("last_name", "lastname", "last", "lname", "surname", "family_name")

        if not first_name and local_part:
            logger.debug(
                "Placeholder fallback: deriving first_name from email "
                "local-part %r because recipient_data has no first_name / "
                "firstname / fname / etc. column. If your CSV has a name "
                "column, check its header capitalization.",
                local_part,
            )
            # Try to extract name from email
            parts = re.split(r"[._\-]", local_part)
            if parts:
                first_name = parts[0].capitalize()
                if len(parts) > 1:
                    last_name = parts[-1].capitalize()

        # Respect explicit full_name / name from recipient_data so callers can
        # override the email-derived default. Without this, an explicit
        # placeholders={"name": "Alice"} would lose to the email-derived "U1".
        full_name = (
            _lookup("full_name", "fullname", "name")
            or f"{first_name} {last_name}".strip()
            or local_part.capitalize()
        )

        # Generate unique IDs
        unique_id = str(uuid.uuid4())
        short_id = unique_id[:8]

        # Hash of email for consistent random values — not a security property,
        # just a deterministic seed for placeholder generation. usedforsecurity=False
        # documents the intent and clears Bandit B324.
        email_hash = hashlib.md5(email.encode(), usedforsecurity=False).hexdigest() if email else ""

        placeholders = {
            # Recipient info
            "email": email,
            "recipient": email,
            "recipient_email": email,  # explicit alias for templates that prefer this name
            "local_part": local_part,
            "username": local_part,
            "domain": domain,
            "domain_name": domain_name,
            "tld": tld,
            "first_name": first_name,
            "firstname": first_name,
            "last_name": last_name,
            "lastname": last_name,
            "full_name": full_name,
            "fullname": full_name,
            "name": full_name,
            "company": _lookup("company", "company_name", "organization", "org")
            or domain_name.capitalize(),
            # Date/Time
            "date": now.strftime("%Y-%m-%d"),
            "date_formatted": now.strftime("%B %d, %Y"),
            "date_short": now.strftime("%m/%d/%Y"),
            "date_eu": now.strftime("%d/%m/%Y"),
            "time": now.strftime("%H:%M:%S"),
            "time_short": now.strftime("%H:%M"),
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": str(int(now.timestamp())),
            "year": now.strftime("%Y"),
            "month": now.strftime("%m"),
            "month_name": now.strftime("%B"),
            "month_short": now.strftime("%b"),
            "day": now.strftime("%d"),
            "day_name": now.strftime("%A"),
            "day_short": now.strftime("%a"),
            "hour": now.strftime("%H"),
            "minute": now.strftime("%M"),
            "second": now.strftime("%S"),
            "week": now.strftime("%W"),
            "quarter": f"Q{(now.month - 1) // 3 + 1}",
            # Unique IDs
            "uuid": unique_id,
            "id": unique_id,
            "short_id": short_id,
            "correlation_id": unique_id,
            "tracking_id": short_id,
            "hash": email_hash[:16],
            # Random numbers
            "random_number": str(random.randint(1000, 9999)),
            "random_6": str(random.randint(100000, 999999)),
            "random_8": str(random.randint(10000000, 99999999)),
            # Calculated
            "domain_capitalized": domain_name.capitalize() if domain_name else "",
            "email_hash": email_hash,
            "initials": "".join([n[0].upper() for n in [first_name, last_name] if n]),
        }

        # Add Faker-generated placeholders if available
        if HAS_FAKER:
            placeholders.update(
                {
                    "random_name": fake.name(),
                    "random_first_name": fake.first_name(),
                    "random_last_name": fake.last_name(),
                    "random_email": fake.email(),
                    "random_company": fake.company(),
                    "random_phone": fake.phone_number(),
                    "random_address": fake.address().replace("\n", ", "),
                    "random_city": fake.city(),
                    "random_country": fake.country(),
                    "random_job": fake.job(),
                    "random_text": fake.text(max_nb_chars=100),
                    "random_sentence": fake.sentence(),
                    "random_word": fake.word(),
                    "random_url": fake.url(),
                    "random_ip": fake.ipv4(),
                    "random_user_agent": fake.user_agent(),
                }
            )
        else:
            # Fallback random data
            names = ["John Smith", "Jane Doe", "Bob Wilson", "Alice Brown"]
            companies = ["Acme Inc", "Global Corp", "Tech Solutions", "Innovation Labs"]
            placeholders.update(
                {
                    "random_name": random.choice(names),
                    "random_first_name": random.choice(["John", "Jane", "Bob", "Alice"]),
                    "random_last_name": random.choice(["Smith", "Doe", "Wilson", "Brown"]),
                    "random_email": f"user{random.randint(1000,9999)}@example.com",
                    "random_company": random.choice(companies),
                    "random_phone": f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
                }
            )

        # Add any custom data from recipient
        for key, value in recipient_data.items():
            if key not in placeholders:
                placeholders[key] = str(value) if value is not None else ""

        # Geolocation + User-Agent enrichment.
        # Source: recipient_data['ip'] / recipient_data['user_agent'] — these
        # come from CSV columns or (later) last-known tracking events backfilled
        # before send. Both are optional; if absent, all derived placeholders
        # resolve to empty strings rather than KeyErroring at substitution.
        # Exposed as flat dotted keys (e.g. ``location.country``) — the
        # ``{{...}}`` regex already accepts dots, so no engine changes needed.
        ip_value = recipient_data.get("ip") or recipient_data.get("ip_address") or ""
        try:
            geo = _get_geo_resolver().resolve(ip_value) if ip_value else {}
        except Exception as e:  # paranoid — resolver should never raise
            logger.warning("Geolocation lookup failed for %r: %s", ip_value, e)
            geo = {}
        for k in (
            "country",
            "country_code",
            "city",
            "region",
            "region_code",
            "timezone",
            "continent",
            "postal",
        ):
            placeholders[f"location.{k}"] = geo.get(k, "") or ""

        ua_value = recipient_data.get("user_agent") or recipient_data.get("ua") or ""
        ua_parsed = _parse_user_agent(ua_value) if ua_value else {}
        for k in ("browser", "browser_version", "os", "os_version", "device"):
            placeholders[f"ua.{k}"] = ua_parsed.get(k, "") or ""

        # Top-level convenience aliases. ``{{location}}`` and ``{{ua}}`` give
        # template authors a one-liner default without forcing them to learn
        # the dotted-key namespace or worry about which sub-fields are
        # populated for a given recipient. Compose with graceful fallback so
        # half-resolved geo (country known, city not) still produces a
        # sensible, non-empty string.
        placeholders["location"] = _compose_location(placeholders)
        placeholders["ua"] = _compose_ua(placeholders)

        return placeholders

    @staticmethod
    def get_builtin_placeholder_catalog() -> "list[dict]":
        """Curated reference catalog for the admin UI.

        Distinct from ``get_builtin_placeholders``: that method generates
        *live values* for a specific recipient on a specific send. This
        method returns a static *description* of every placeholder the
        engine understands, so the UI can render a discoverable list.

        Each item: ``{name, category, description, sample}``. Sample is a
        representative literal value (not a live one) the operator can
        glance at to know what to expect in their rendered email.

        Adding a new built-in elsewhere? Add it here too — the contract is
        "if the engine resolves it, the operator can see it listed."
        """
        return [
            # ── Recipient ─────────────────────────────────────────────
            {
                "name": "email",
                "category": "Recipient",
                "description": "The recipient email address.",
                "sample": "alice@acme.com",
            },
            {
                "name": "recipient",
                "category": "Recipient",
                "description": "Alias for {{email}}.",
                "sample": "alice@acme.com",
            },
            {
                "name": "recipient_email",
                "category": "Recipient",
                "description": "Alias for {{email}} (explicit form).",
                "sample": "alice@acme.com",
            },
            {
                "name": "first_name",
                "category": "Recipient",
                "description": "First name from CSV, or derived from local-part.",
                "sample": "Alice",
            },
            {
                "name": "firstname",
                "category": "Recipient",
                "description": "Alias for {{first_name}}.",
                "sample": "Alice",
            },
            {
                "name": "last_name",
                "category": "Recipient",
                "description": "Last name from CSV, or derived from local-part.",
                "sample": "Brown",
            },
            {
                "name": "lastname",
                "category": "Recipient",
                "description": "Alias for {{last_name}}.",
                "sample": "Brown",
            },
            {
                "name": "full_name",
                "category": "Recipient",
                "description": 'CSV "full_name"/"name", else first+last, else local-part.',
                "sample": "Alice Brown",
            },
            {
                "name": "fullname",
                "category": "Recipient",
                "description": "Alias for {{full_name}}.",
                "sample": "Alice Brown",
            },
            {
                "name": "name",
                "category": "Recipient",
                "description": "Alias for {{full_name}}.",
                "sample": "Alice Brown",
            },
            {
                "name": "initials",
                "category": "Recipient",
                "description": "Uppercase initials from first/last name.",
                "sample": "AB",
            },
            {
                "name": "company",
                "category": "Recipient",
                "description": 'CSV "company", else capitalized domain root.',
                "sample": "Acme",
            },
            {
                "name": "local_part",
                "category": "Recipient",
                "description": "Email part before @.",
                "sample": "alice.smith",
            },
            {
                "name": "username",
                "category": "Recipient",
                "description": "Alias for {{local_part}}.",
                "sample": "alice.smith",
            },
            {
                "name": "domain",
                "category": "Recipient",
                "description": "Full domain after @.",
                "sample": "example.com",
            },
            {
                "name": "domain_name",
                "category": "Recipient",
                "description": "Domain without TLD.",
                "sample": "example",
            },
            {
                "name": "domain_capitalized",
                "category": "Recipient",
                "description": "Capitalized domain without TLD.",
                "sample": "Example",
            },
            {
                "name": "tld",
                "category": "Recipient",
                "description": "Top-level domain.",
                "sample": "com",
            },
            # ── Render-time extras (engine appends these per-send) ────
            {
                "name": "unsubscribe_url",
                "category": "Engine extras",
                "description": "Generated one-click unsubscribe link.",
                "sample": "https://mercury.local/track/unsubscribe/...",
            },
            {
                "name": "unsubscribe_link",
                "category": "Engine extras",
                "description": "Alias for {{unsubscribe_url}}.",
                "sample": "https://mercury.local/track/unsubscribe/...",
            },
            {
                "name": "link",
                "category": "Engine extras",
                "description": "Trackable link (if using auto-tracking).",
                "sample": "https://mercury.local/track/...",
            },
            {
                "name": "url",
                "category": "Engine extras",
                "description": "Alias for {{link}}.",
                "sample": "https://example.com/u/42",
            },
            {
                "name": "qr_code",
                "category": "Engine extras",
                "description": "<img> tag for the QR code (body only).",
                "sample": '<img src="data:image/png;base64,..." />',
            },
            {
                "name": "qr_code_url",
                "category": "Engine extras",
                "description": "Raw data: URL of the QR code (for headers).",
                "sample": "data:image/png;base64,...",
            },
            {
                "name": "company_logo",
                "category": "Engine extras",
                "description": "<img> tag for the pinned/auto-fetched logo.",
                "sample": '<img src="data:image/png;base64,..." />',
            },
            {
                "name": "company_logo_url",
                "category": "Engine extras",
                "description": "Raw data: URL of the logo (for headers).",
                "sample": "data:image/png;base64,...",
            },
            {
                "name": "brand",
                "category": "Engine extras",
                "description": "Logo when available, else styled company name.",
                "sample": '<span class="company-name">Acme</span>',
            },
            # ── Date / Time ──────────────────────────────────────────
            {
                "name": "date",
                "category": "Date/Time",
                "description": "Today in YYYY-MM-DD.",
                "sample": "2026-05-21",
            },
            {
                "name": "date_formatted",
                "category": "Date/Time",
                "description": 'Today as "May 21, 2026".',
                "sample": "May 21, 2026",
            },
            {
                "name": "date_short",
                "category": "Date/Time",
                "description": "Today in MM/DD/YYYY (US).",
                "sample": "05/21/2026",
            },
            {
                "name": "date_eu",
                "category": "Date/Time",
                "description": "Today in DD/MM/YYYY (EU).",
                "sample": "21/05/2026",
            },
            {
                "name": "time",
                "category": "Date/Time",
                "description": "Current time HH:MM:SS (UTC).",
                "sample": "14:30:00",
            },
            {
                "name": "time_short",
                "category": "Date/Time",
                "description": "Current time HH:MM (UTC).",
                "sample": "14:30",
            },
            {
                "name": "datetime",
                "category": "Date/Time",
                "description": "Full datetime YYYY-MM-DD HH:MM:SS (UTC).",
                "sample": "2026-05-21 14:30:00",
            },
            {
                "name": "timestamp",
                "category": "Date/Time",
                "description": "Unix timestamp (seconds).",
                "sample": "1747837800",
            },
            {
                "name": "year",
                "category": "Date/Time",
                "description": "Current year (4-digit).",
                "sample": "2026",
            },
            {
                "name": "month",
                "category": "Date/Time",
                "description": "Current month (zero-padded).",
                "sample": "05",
            },
            {
                "name": "month_name",
                "category": "Date/Time",
                "description": "Full month name.",
                "sample": "May",
            },
            {
                "name": "month_short",
                "category": "Date/Time",
                "description": "Abbreviated month name.",
                "sample": "May",
            },
            {
                "name": "day",
                "category": "Date/Time",
                "description": "Day of month (zero-padded).",
                "sample": "21",
            },
            {
                "name": "day_name",
                "category": "Date/Time",
                "description": "Full day name.",
                "sample": "Thursday",
            },
            {
                "name": "day_short",
                "category": "Date/Time",
                "description": "Abbreviated day name.",
                "sample": "Thu",
            },
            {
                "name": "hour",
                "category": "Date/Time",
                "description": "Current hour (00-23).",
                "sample": "14",
            },
            {
                "name": "minute",
                "category": "Date/Time",
                "description": "Current minute.",
                "sample": "30",
            },
            {
                "name": "second",
                "category": "Date/Time",
                "description": "Current second.",
                "sample": "00",
            },
            {
                "name": "week",
                "category": "Date/Time",
                "description": "Week of year.",
                "sample": "21",
            },
            {
                "name": "quarter",
                "category": "Date/Time",
                "description": "Quarter (Q1-Q4).",
                "sample": "Q2",
            },
            # ── IDs / hashes ─────────────────────────────────────────
            {
                "name": "uuid",
                "category": "IDs",
                "description": "New UUID4, regenerated per send.",
                "sample": "b3e1c7a9-d2f5-4f8b-9c1e-...",
            },
            {
                "name": "id",
                "category": "IDs",
                "description": "Alias for {{uuid}}.",
                "sample": "b3e1c7a9-...",
            },
            {
                "name": "short_id",
                "category": "IDs",
                "description": "First 8 chars of {{uuid}}.",
                "sample": "b3e1c7a9",
            },
            {
                "name": "correlation_id",
                "category": "IDs",
                "description": "Send correlation id (matches tracking + logs).",
                "sample": "b3e1c7a9-...",
            },
            {
                "name": "tracking_id",
                "category": "IDs",
                "description": "Short id used in tracking links.",
                "sample": "b3e1c7a9",
            },
            {
                "name": "hash",
                "category": "IDs",
                "description": "First 16 chars of MD5(email).",
                "sample": "a1b2c3d4e5f60718",
            },
            {
                "name": "email_hash",
                "category": "IDs",
                "description": "Full MD5(email) hex.",
                "sample": "a1b2c3d4e5f607189a8b7c6d5e4f3a2b",
            },
            # ── Random ───────────────────────────────────────────────
            {
                "name": "random_number",
                "category": "Random",
                "description": "Random 4-digit integer.",
                "sample": "4729",
            },
            {
                "name": "random_6",
                "category": "Random",
                "description": "Random 6-digit integer.",
                "sample": "472913",
            },
            {
                "name": "random_8",
                "category": "Random",
                "description": "Random 8-digit integer.",
                "sample": "47291338",
            },
            {
                "name": "random_name",
                "category": "Random",
                "description": "Random person name (Faker if installed).",
                "sample": "Jane Doe",
            },
            {
                "name": "random_company",
                "category": "Random",
                "description": "Random company name.",
                "sample": "Acme Industries",
            },
            {
                "name": "random_email",
                "category": "Random",
                "description": "Random email address.",
                "sample": "user1234@example.com",
            },
            {
                "name": "random_url",
                "category": "Random",
                "description": "Random URL (Faker only).",
                "sample": "https://example.com/foo",
            },
            # ── Geo / UA (require enrichment) ────────────────────────
            {
                "name": "location",
                "category": "Geo / UA",
                "description": '"City, Region, Country" composite. Needs IP enrichment.',
                "sample": "San Francisco, CA, United States",
            },
            {
                "name": "location.country",
                "category": "Geo / UA",
                "description": "Recipient country (from IP).",
                "sample": "United States",
            },
            {
                "name": "location.city",
                "category": "Geo / UA",
                "description": "Recipient city.",
                "sample": "San Francisco",
            },
            {
                "name": "location.region",
                "category": "Geo / UA",
                "description": "Recipient region / state.",
                "sample": "California",
            },
            {
                "name": "location.timezone",
                "category": "Geo / UA",
                "description": "Recipient IANA timezone.",
                "sample": "America/Los_Angeles",
            },
            {
                "name": "ua",
                "category": "Geo / UA",
                "description": '"Browser on OS" composite. Needs UA enrichment.',
                "sample": "Chrome on macOS",
            },
            {
                "name": "ua.browser",
                "category": "Geo / UA",
                "description": "Parsed browser family.",
                "sample": "Chrome",
            },
            {
                "name": "ua.os",
                "category": "Geo / UA",
                "description": "Parsed OS family.",
                "sample": "macOS",
            },
            {
                "name": "ua.device",
                "category": "Geo / UA",
                "description": "Parsed device class.",
                "sample": "Mac",
            },
        ]

    def process(
        self,
        template: str,
        recipient_data: Optional[Dict[str, Any]] = None,
        extra_placeholders: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Process template and replace all placeholders.

        Args:
            template: Template string with {{placeholders}}
            recipient_data: Recipient-specific data
            extra_placeholders: Additional placeholder values

        Returns:
            Processed string with placeholders replaced
        """
        # Build placeholder dict
        placeholders = self.get_builtin_placeholders(recipient_data)
        placeholders.update(self.static_placeholders)

        if extra_placeholders:
            placeholders.update(extra_placeholders)

        # Add custom generators
        for name, generator in self._custom_generators.items():
            try:
                placeholders[name] = generator()
            except Exception as e:
                logger.warning(f"Custom generator '{name}' failed: {e}")
                placeholders[name] = ""

        # Replace placeholders. Values are coerced to str at the boundary
        # so static placeholders or custom-generator results that return
        # int/datetime/None don't crash re.sub (which requires a str
        # return value).
        def replace_placeholder(match):
            key = match.group(1).strip()
            if key not in placeholders:
                return match.group(0)
            value = placeholders[key]
            if value is None:
                return ""
            return value if isinstance(value, str) else str(value)

        result = re.sub(r"\{\{([^}]+)\}\}", replace_placeholder, template)

        return result

    def get_used_placeholders(self, template: str) -> List[str]:
        """Extract list of placeholder names used in template."""
        pattern = r"\{\{([^}]+)\}\}"
        matches = re.findall(pattern, template)
        return [m.strip() for m in matches]

    def validate_placeholders(
        self, template: str, available_placeholders: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Validate that all placeholders in template are available.

        Returns:
            Dict with 'valid', 'used', 'missing', 'available'
        """
        used = self.get_used_placeholders(template)
        builtin = set(self.get_builtin_placeholders().keys())
        static = set(self.static_placeholders.keys())
        custom = set(self._custom_generators.keys())

        if available_placeholders:
            available = set(available_placeholders) | builtin | static | custom
        else:
            available = builtin | static | custom

        missing = [p for p in used if p not in available]

        return {
            "valid": len(missing) == 0,
            "used": used,
            "missing": missing,
            "available": list(available),
        }


def generate_identity() -> Dict[str, str]:
    """
    Generate a complete random identity.

    Returns:
        Dict with full identity information
    """
    if HAS_FAKER:
        first = fake.first_name()
        last = fake.last_name()
        email_user = f"{first.lower()}.{last.lower()}"

        return {
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "email": f"{email_user}@{fake.domain_name()}",
            "phone": fake.phone_number(),
            "company": fake.company(),
            "job_title": fake.job(),
            "address": fake.address().replace("\n", ", "),
            "city": fake.city(),
            "country": fake.country(),
            "uuid": str(uuid.uuid4()),
        }
    else:
        first_names = ["John", "Jane", "Michael", "Sarah", "David", "Emily"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis"]

        first = random.choice(first_names)
        last = random.choice(last_names)

        return {
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}@example.com",
            "phone": f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
            "company": "Example Corp",
            "job_title": "Employee",
            "uuid": str(uuid.uuid4()),
        }


def apply_placeholders(template: str, placeholders: Dict[str, Any]) -> str:
    """
    Simple placeholder replacement function.

    Args:
        template: Template string
        placeholders: Dict of placeholder values

    Returns:
        Processed string
    """
    result = template
    for key, value in placeholders.items():
        result = result.replace(f"{{{{{key}}}}}", str(value) if value is not None else "")
    return result
