"""Lightweight User-Agent string parser.

Why this exists separately from a full ua-parser dependency: the UA strings we
get come from prior tracking events on this server (recipient context). We
need browser / OS / device buckets at the granularity templates actually use
("Chrome", "macOS", "Mobile"), not the long-tail of every UA variant. A few
regexes covering ~95% of real-world UAs is far cheaper than pulling in
ua-parser + its yaml regex bundle, and it has no install-time footprint.

Callers that need higher fidelity can swap in `ua-parser` by reimplementing
``parse()`` — the return shape is the contract.
"""

from __future__ import annotations

import re
from typing import Optional

# Order matters: more specific patterns must come before generic fallbacks.
# (e.g., Edge before Chrome — Edge UAs include "Chrome".)
_BROWSER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/(\S+)")),
    ("Opera", re.compile(r"OPR/(\S+)|Opera/(\S+)")),
    ("Firefox", re.compile(r"Firefox/(\S+)")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/(\S+)")),
    ("Chrome", re.compile(r"Chrome/(\S+)")),
    ("Safari", re.compile(r"Version/(\S+).*Safari/")),
    ("IE", re.compile(r"MSIE (\S+);|Trident/.*rv:(\S+)\)")),
]

_OS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # iOS first — "iPhone OS 17_0" — must come before "Mac OS X" fallback.
    ("iOS", re.compile(r"(?:iPhone|iPad|iPod) (?:CPU )?OS (\d+[_\d]*)")),
    ("Android", re.compile(r"Android (\d+(?:\.\d+)*)")),
    ("Windows", re.compile(r"Windows NT (\d+\.\d+)")),
    ("macOS", re.compile(r"Mac OS X (\d+[_\d]*)")),
    ("Linux", re.compile(r"(Linux)")),
    ("ChromeOS", re.compile(r"CrOS \S+ (\S+)")),
]

# Windows NT version → marketing name, since "10.0" is unreadable in templates.
_WINDOWS_NT_MAP = {
    "10.0": "10",
    "6.3": "8.1",
    "6.2": "8",
    "6.1": "7",
}

_MOBILE_HINT = re.compile(r"Mobile|Android|iPhone|iPod|Opera Mini|IEMobile", re.IGNORECASE)
_TABLET_HINT = re.compile(r"iPad|Tablet", re.IGNORECASE)
_BOT_HINT = re.compile(
    r"bot|crawler|spider|slurp|curl|wget|python-requests|httpie", re.IGNORECASE
)


def _classify_device(ua: str) -> str:
    if _BOT_HINT.search(ua):
        return "Bot"
    if _TABLET_HINT.search(ua):
        return "Tablet"
    if _MOBILE_HINT.search(ua):
        return "Mobile"
    return "Desktop"


def _normalize_version(raw: Optional[str]) -> str:
    if not raw:
        return ""
    # iOS / macOS use underscores ("17_0"). Templates expect dots.
    return raw.replace("_", ".")


def parse(ua: Optional[str]) -> dict[str, str]:
    """Parse a UA string into a flat dict.

    Returns the same key set whether parsing succeeds or not, so
    downstream placeholder lookups never KeyError. All values are strings;
    unknown buckets are empty strings (not ``None``) so they render cleanly
    when substituted into a template.
    """
    empty = {
        "browser": "",
        "browser_version": "",
        "os": "",
        "os_version": "",
        "device": "",
        "raw": ua or "",
    }
    if not ua:
        return empty

    out = dict(empty)

    for name, pat in _BROWSER_PATTERNS:
        m = pat.search(ua)
        if m:
            out["browser"] = name
            # First non-None capture group is the version.
            version = next((g for g in m.groups() if g), "")
            out["browser_version"] = version
            break

    for name, pat in _OS_PATTERNS:
        m = pat.search(ua)
        if m:
            out["os"] = name
            version = m.group(1) if m.lastindex else ""
            if name == "Windows":
                out["os_version"] = _WINDOWS_NT_MAP.get(version, version)
            elif name == "Linux":
                out["os_version"] = ""
            else:
                out["os_version"] = _normalize_version(version)
            break

    out["device"] = _classify_device(ua)
    return out
