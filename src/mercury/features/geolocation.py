"""IP → geolocation resolver, backed by MaxMind GeoLite2.

Why MaxMind GeoLite2 specifically:
- Offline lookup → no per-recipient HTTP at send time, no rate limit, no
  recipient-IP exfiltration to a third party.
- The DB ships as a single ``.mmdb`` file (~70 MB City DB).
- Free, with a license key.

The resolver fails open: if ``geoip2`` isn't installed, or the DB env var is
unset, or the file is missing/corrupt, every lookup returns the same empty
shape. That keeps the placeholder engine from KeyErroring and lets the
campaign send proceed — geo is best-effort enrichment, never a blocker.

The resolver is **not** in the install-base by default. Operators opt in
via the ``geo`` extra::

    pip install -e .[geo]

and point ``MERCURY_GEOIP_DB`` at their downloaded ``GeoLite2-City.mmdb``.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Environment variable that points to the .mmdb file. Documented in CLAUDE.md.
_GEOIP_DB_ENV = "MERCURY_GEOIP_DB"

# Empty result shape — kept identical to a successful lookup so the
# placeholder engine never has to special-case "geo unavailable".
_EMPTY: dict[str, str] = {
    "country": "",
    "country_code": "",
    "city": "",
    "region": "",
    "region_code": "",
    "timezone": "",
    "continent": "",
    "postal": "",
}


class GeoResolver:
    """Thread-safe lazy-loaded GeoLite2 City resolver.

    One reader is shared process-wide (``_singleton`` below). The reader is
    the expensive thing to construct — opening it does an mmap + index
    read; instances themselves are cheap, so reuse via ``get_resolver()``.
    """

    def __init__(self, db_path: Optional[str] = None):
        # Resolve at construction so subsequent env-var changes don't
        # surprise the campaign mid-send.
        self.db_path = db_path or os.environ.get(_GEOIP_DB_ENV, "")
        self._reader = None
        self._available: Optional[bool] = None
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, str]] = {}
        self._cache_keys: list[str] = []

    def _load(self) -> bool:
        """Open the .mmdb on first use. Returns True if usable."""
        if self._available is not None:
            return self._available

        with self._lock:
            if self._available is not None:
                return self._available

            if not self.db_path:
                logger.info(
                    "Geolocation disabled: %s not set — {{location.*}} "
                    "placeholders will resolve to empty strings.",
                    _GEOIP_DB_ENV,
                )
                self._available = False
                return False

            try:
                import geoip2.database  # type: ignore[import-not-found]
            except ImportError:
                logger.warning(
                    "Geolocation disabled: 'geoip2' not installed. "
                    "Install with `pip install -e .[geo]`."
                )
                self._available = False
                return False

            if not os.path.isfile(self.db_path):
                logger.warning(
                    "Geolocation disabled: %s=%r is not a file.",
                    _GEOIP_DB_ENV,
                    self.db_path,
                )
                self._available = False
                return False

            try:
                self._reader = geoip2.database.Reader(self.db_path)
                self._available = True
                logger.info("Geolocation enabled: loaded %s", self.db_path)
                return True
            except Exception as e:
                logger.warning("Geolocation disabled: failed to open %s: %s", self.db_path, e)
                self._available = False
                return False

    def resolve(self, ip: Optional[str]) -> dict[str, str]:
        """Look up ``ip``. Always returns the full key set; empty on miss.

        Private/loopback addresses and non-IP strings short-circuit to empty
        rather than going through the reader — avoids logspam on local
        traffic and keeps the hot path tight.
        """
        if not ip or not self._load():
            return dict(_EMPTY)

        # Cheap pre-filter: skip the reader for traffic that can't possibly
        # geolocate (loopback, RFC1918, link-local). MaxMind would just
        # raise AddressNotFoundError, but checking here avoids both the
        # exception cost and a noisy "address not in database" log line.
        if (
            ip.startswith(("10.", "127.", "192.168.", "169.254.", "::1", "fe80:"))
            or ip.startswith(("172.",))
            and _is_rfc1918_172(ip)
        ):
            return dict(_EMPTY)

        # Lock cache access to ensure thread-safety
        with self._lock:
            if ip in self._cache:
                # Move to end of key list (MRU)
                try:
                    self._cache_keys.remove(ip)
                except ValueError:
                    pass
                self._cache_keys.append(ip)
                return dict(self._cache[ip])

        try:
            r = self._reader.city(ip)  # type: ignore[union-attr]
            res = {
                "country": (r.country.name or "") if r.country else "",
                "country_code": (r.country.iso_code or "") if r.country else "",
                "city": (r.city.name or "") if r.city else "",
                "region": (r.subdivisions.most_specific.name or "") if r.subdivisions else "",
                "region_code": (r.subdivisions.most_specific.iso_code or "") if r.subdivisions else "",
                "timezone": (r.location.time_zone or "") if r.location else "",
                "continent": (r.continent.name or "") if r.continent else "",
                "postal": (r.postal.code or "") if r.postal else "",
            }
        except Exception:
            res = dict(_EMPTY)

        with self._lock:
            # Evict oldest if cache size exceeded
            if len(self._cache) >= 1024:
                if self._cache_keys:
                    oldest = self._cache_keys.pop(0)
                    self._cache.pop(oldest, None)

            self._cache[ip] = res
            self._cache_keys.append(ip)
            return dict(res)

    def close(self) -> None:
        with self._lock:
            self._cache.clear()
            self._cache_keys.clear()
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None


def _is_rfc1918_172(ip: str) -> bool:
    """172.16.0.0 – 172.31.255.255. Other 172.x is public."""
    try:
        second = int(ip.split(".", 2)[1])
    except (ValueError, IndexError):
        return False
    return 16 <= second <= 31


# Process-wide singleton. Built lazily so importing this module never opens
# a file descriptor — matters in tests and CLI paths that don't need geo.
_singleton: Optional[GeoResolver] = None
_singleton_lock = threading.Lock()


def get_resolver() -> GeoResolver:
    """Return the process-wide GeoResolver, creating it on first call."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = GeoResolver()
    return _singleton


def reset_resolver_for_tests() -> None:
    """Test-only: drop the singleton so tests can swap in a different DB."""
    global _singleton
    with _singleton_lock:
        if _singleton is not None:
            _singleton.close()
        _singleton = None
