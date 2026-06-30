"""Business metrics for the send pipeline.

Defined in ``utils`` (not ``web``) so the engine and services can record
without taking a web-layer dependency. They register on prometheus-client's
default registry, so ``web/metrics.py``'s ``/metrics`` endpoint exposes them
automatically — single-worker means that in-process registry is complete.

Every ``record_*`` / ``campaign_*`` helper is defensive: a metrics failure (or
prometheus-client not being installed) must never disrupt a send. The module is
import-guarded so a core install without the observability extra still works.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge

    _AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _AVAILABLE = False

if _AVAILABLE:
    EMAILS_SENT = Counter(
        "mercury_emails_sent_total",
        "Emails successfully sent.",
    )
    EMAILS_FAILED = Counter(
        "mercury_emails_failed_total",
        "Emails that failed to send, bucketed by failure category.",
        ["type"],
    )
    CAMPAIGNS_ACTIVE = Gauge(
        "mercury_campaigns_active",
        "Campaigns currently executing in this process.",
    )

# Bounded set so the {type} label can't explode cardinality on unexpected
# error_type values (anything else collapses to "other").
_FAIL_TYPES = frozenset({"transient", "permanent", "unknown", "exception"})


def record_send_result(success: bool, error_type: Optional[str] = None) -> None:
    """Record one email send outcome (success, or failure by category)."""
    if not _AVAILABLE:
        return
    try:
        if success:
            EMAILS_SENT.inc()
        else:
            bucket = error_type if error_type in _FAIL_TYPES else "other"
            EMAILS_FAILED.labels(type=bucket).inc()
    except Exception:  # pragma: no cover - metrics must never break a send
        logger.debug("record_send_result metric failed", exc_info=True)


def campaign_started() -> None:
    """Increment the active-campaigns gauge (call when execution begins)."""
    if not _AVAILABLE:
        return
    try:
        CAMPAIGNS_ACTIVE.inc()
    except Exception:  # pragma: no cover
        logger.debug("campaign_started metric failed", exc_info=True)


def campaign_finished() -> None:
    """Decrement the active-campaigns gauge (call in a finally when done)."""
    if not _AVAILABLE:
        return
    try:
        CAMPAIGNS_ACTIVE.dec()
    except Exception:  # pragma: no cover
        logger.debug("campaign_finished metric failed", exc_info=True)
