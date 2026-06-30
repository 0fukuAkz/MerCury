"""Prometheus metrics endpoint and HTTP instrumentation.

MerCury runs single-worker (``-w 1`` — see run.py and the create_app
production preflight), so the default in-process registry is correct with no
multiprocess gymnastics: every request *and* the background send loop share
one process, so the counters are global and complete. Scrape ``GET /metrics``.

Access: the endpoint is optionally gated by ``METRICS_TOKEN`` (``Authorization:
Bearer <token>`` or ``?token=<token>``). When unset it is open, so either set a
token or block ``/metrics`` at your ingress. The whole module is import-guarded
— a core install without prometheus-client still boots, and /metrics returns
501 rather than crashing.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from typing import Optional

from flask import Blueprint, Flask, Response, request

logger = logging.getLogger(__name__)

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _PROM_AVAILABLE = False


metrics_bp = Blueprint("metrics", __name__)


if _PROM_AVAILABLE:
    _REQUESTS = Counter(
        "mercury_http_requests_total",
        "Total HTTP requests processed, by method, route template and status.",
        ["method", "endpoint", "status"],
    )
    _LATENCY = Histogram(
        "mercury_http_request_duration_seconds",
        "HTTP request latency in seconds, by method and route template.",
        ["method", "endpoint"],
    )


def _authorized() -> bool:
    """True if the current request may read ``/metrics``.

    Open when ``METRICS_TOKEN`` is unset; otherwise require it via the
    ``Authorization: Bearer`` header or a ``?token=`` query arg, compared in
    constant time so the token can't be recovered by timing.
    """
    token = os.environ.get("METRICS_TOKEN", "").strip()
    if not token:
        return True
    header = request.headers.get("Authorization", "")
    presented = (
        header[len("Bearer ") :] if header.startswith("Bearer ") else request.args.get("token", "")
    )
    return hmac.compare_digest(presented, token)


@metrics_bp.route("/metrics")
def metrics() -> Response:
    """Expose metrics in the Prometheus text exposition format."""
    if not _PROM_AVAILABLE:
        return Response(
            "prometheus-client not installed; pip install mercury[observability]\n",
            status=501,
            mimetype="text/plain",
        )
    if not _authorized():
        return Response("unauthorized\n", status=401, mimetype="text/plain")
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def init_metrics(app: Flask) -> None:
    """Register the ``/metrics`` route and per-request instrumentation.

    Safe and cheap to call unconditionally. When prometheus-client is missing,
    the blueprint is still registered (so ``/metrics`` returns a clear 501) but
    no timing hooks are installed.
    """
    app.register_blueprint(metrics_bp)
    if not _PROM_AVAILABLE:
        return

    @app.before_request
    def _start_timer() -> None:
        request._mercury_metrics_start = time.perf_counter()  # type: ignore[attr-defined]

    @app.after_request
    def _record_metrics(response: Response) -> Response:
        # Label by the *route template* (e.g. /api/smtp/<name>), never the
        # concrete path — otherwise an unbounded set of server names / ids would
        # explode label cardinality and OOM the scrape.
        endpoint = request.url_rule.rule if request.url_rule else "<unmatched>"
        start: Optional[float] = getattr(request, "_mercury_metrics_start", None)
        if start is not None:
            _LATENCY.labels(request.method, endpoint).observe(time.perf_counter() - start)
        _REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
        return response
