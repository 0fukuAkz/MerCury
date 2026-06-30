"""Optional Sentry error tracking.

Sentry activates only when ``SENTRY_DSN`` is set, so development, tests, and
DSN-less installs are entirely unaffected. :func:`init_sentry` is safe to call
unconditionally from the app factory and never raises — observability must not
be able to take down the application it observes.

Install the dependency with ``pip install mercury[observability]`` (it is
already bundled in the production ``requirements.txt`` / Docker image).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _detect_release() -> Optional[str]:
    """Best-effort release tag for Sentry (the installed package version)."""
    explicit = os.environ.get("MERCURY_RELEASE", "").strip()
    if explicit:
        return explicit
    try:
        from importlib.metadata import version

        return version("mercury")
    except Exception:
        return None


def init_sentry() -> bool:
    """Initialise Sentry iff ``SENTRY_DSN`` is set and the SDK is installed.

    Returns ``True`` when Sentry was activated, ``False`` otherwise. Never
    raises: a misconfigured DSN, a missing dependency, or an SDK-internal error
    is logged and swallowed so the app still boots.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; error tracking "
            "disabled. Install mercury[observability]."
        )
        return False

    try:
        traces_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0") or "0")
    except ValueError:
        traces_rate = 0.0

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.environ.get("FLASK_ENV", "development"),
            release=_detect_release(),
            integrations=[
                FlaskIntegration(),
                # INFO+ becomes breadcrumbs; ERROR+ is captured as an event.
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            traces_sample_rate=traces_rate,
            # MerCury handles recipient PII; never let it leak into Sentry by
            # default. Operators can opt in explicitly if their DPA permits.
            send_default_pii=False,
        )
    except Exception as exc:  # pragma: no cover - defensive; must not crash boot
        logger.warning("Sentry initialisation failed (%s); continuing without it.", exc)
        return False

    logger.info(
        "Sentry error tracking enabled (environment=%s).",
        os.environ.get("FLASK_ENV", "development"),
    )
    return True
