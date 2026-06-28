"""Boot-seam integration tests — exercise the REAL AppContext.

The unit ``app`` fixture in conftest patches ``get_app_context`` to a
MagicMock, so ``AppContext.initialize()`` never runs in the normal suite.
That method is exactly where ``csrf.init_app()`` and the api/tracking/health
CSRF exemptions live — the seam the production CSRF and CSP incidents lived
in, and one no unit test could ever catch (mocked container + the test
client enforces no CSP).

These tests build the app with the real DI container (DB boot patched out —
the CSRF/header wiring needs no database) so that seam is actually verified.
A POST to the api blueprint reaching auth (401) instead of CSRF (400) is the
precise regression guard for "every dashboard button suddenly does nothing".
"""

import os
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def real_app():
    from mercury.app_context import reset_app_context
    from mercury.web import extensions as ext
    from mercury.web.app import create_app

    env = {"SECRET_KEY": "x" * 40, "FLASK_ENV": "testing", "API_KEYS": "seam-test-key"}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    # Fresh, un-mocked DI container. We patch out boot side effects that would
    # leak into other tests or threads, keeping ONLY the wiring under test:
    #   - init_db / alembic: the CSRF/header seam needs no database, and the
    #     401 auth path short-circuits before any query.
    #   - socketio.init_app / register_socketio_events / start_emit_bridge /
    #     start_background_loop: these mutate the module-level socketio
    #     singleton and spawn threads; rebinding socketio to this throwaway
    #     app breaks test_socketio.py. csrf + limiter stay real (csrf is the
    #     seam under test).
    reset_app_context()
    with patch("mercury.web.app.init_db"), patch("mercury.web.app.alembic_command"), patch(
        "mercury.web.app.register_socketio_events"
    ), patch("mercury.web.app.start_background_loop"), patch(
        "mercury.web.extensions.start_emit_bridge"
    ), patch.object(ext.socketio, "init_app"):
        app = create_app(config={"WTF_CSRF_ENABLED": True})

    try:
        yield app
    finally:
        reset_app_context()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_csrf_is_actually_initialized(real_app):
    """AppContext.initialize() must register CSRF on the real app."""
    assert "csrf" in real_app.extensions


def test_api_tracking_health_blueprints_are_csrf_exempt(real_app):
    from mercury.web.extensions import csrf

    exempt = {getattr(bp, "name", bp) for bp in getattr(csrf, "_exempt_blueprints", set())}
    assert {"api", "tracking", "health"} <= exempt


def test_api_post_reaches_auth_not_csrf(real_app):
    """A POST to the (exempt) api blueprint must hit auth (401), not CSRF (400).

    If the exemption regresses, browser mutations across every section get a
    400 'CSRF token missing' instead — the SMTP-section outage.
    """
    resp = real_app.test_client().post("/api/smtp/test/whatever")
    assert resp.status_code == 401
    assert resp.get_json().get("error") == "Authentication required"


def test_csp_permits_inline_handlers_on_real_boot(real_app):
    """The real after_request must emit an inline-handler-compatible CSP."""
    resp = real_app.test_client().get("/api/smtp")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "'unsafe-inline'" in csp
    assert "nonce-" not in csp
    assert resp.headers.get("X-Frame-Options") == "DENY"
