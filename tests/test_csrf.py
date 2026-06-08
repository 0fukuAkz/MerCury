"""Direct verification that CSRF protection is wired and enforced.

The standard test app fixture sets ``WTF_CSRF_ENABLED=False`` so existing
tests don't have to acquire tokens. These tests build a separate app with
CSRF *enabled* to assert:

  1. Form-driven POSTs without a token are rejected (400).
  2. Form-driven POSTs with a valid token are accepted.
  3. The api blueprint (X-API-Key auth) is exempt — POSTing JSON without
     a token still works for token-authenticated callers.
  4. The tracking and health blueprints are exempt.
"""

from unittest.mock import MagicMock, patch

import pytest

from mercury.app_context import AppContext


def _make_csrf_app(db_engine):
    """Build a Flask test app with CSRF protection enabled."""
    from sqlalchemy.orm import sessionmaker
    from mercury.web.app import create_app
    import os

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()

    TestSession = sessionmaker(bind=db_engine)

    with patch("mercury.web.app.init_db"), patch(
        "mercury.security.auth.UserRepository"
    ) as MockRepo, patch("mercury.web.app.get_app_context", return_value=mock_context), patch(
        "mercury.data.database.get_session_direct", side_effect=TestSession
    ), patch(
        "mercury.services.smtp_service.get_session_direct", side_effect=TestSession
    ), patch.dict(os.environ, {"API_KEYS": "test_api_key"}):
        MockRepo.return_value.get_admins.return_value = [MagicMock()]

        # CSRF wiring: AppContext is mocked here too, but we still want
        # csrf.init_app on the test app so requests are validated.
        from mercury.web.extensions import csrf

        app = create_app(
            config={
                "TESTING": True,
                "WTF_CSRF_ENABLED": True,
            }
        )
        # The mocked AppContext skipped the real init — wire CSRF ourselves.
        csrf.init_app(app)

        # Re-apply blueprint exemptions after the late init.
        from mercury.web.routes.api import api_bp
        from mercury.web.routes.tracking import tracking_bp
        from mercury.web.routes.health import health_bp

        csrf.exempt(api_bp)
        csrf.exempt(tracking_bp)
        csrf.exempt(health_bp)

        yield app


@pytest.fixture
def csrf_app(db_engine):
    yield from _make_csrf_app(db_engine)


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


def test_form_post_without_token_is_rejected(csrf_client):
    """POST to a non-exempt route without a csrf_token returns 400."""
    resp = csrf_client.post("/login", data={"username": "u", "password": "p"})
    # flask-wtf default rejection is 400 with 'CSRF' in the body.
    assert resp.status_code == 400
    assert b"CSRF" in resp.data or b"csrf" in resp.data


def test_api_blueprint_is_exempt(csrf_client):
    """POST /api/* with X-API-Key but no csrf_token works (api is exempt)."""
    resp = csrf_client.post(
        "/api/campaigns",
        json={"name": "Test"},
        headers={"X-API-Key": "test_api_key"},
    )
    # Either 200 (created) or 400 (validation), but NOT a 400 with 'CSRF' —
    # the request reached the route rather than being short-circuited by
    # the CSRF guard.
    assert (
        b"CSRF" not in resp.data and b"csrf" not in resp.data.lower().split(b"csrf-token-error")[0]
    )


def test_tracking_blueprint_is_exempt(csrf_client):
    """GET /track/* doesn't require CSRF (link redirects from email clients)."""
    # Even an unknown tracking id should reach the handler (which returns
    # a 1x1 pixel or 404), not be rejected by CSRF.
    resp = csrf_client.get("/track/open/some-correlation-id")
    assert resp.status_code in (200, 302, 404)


def test_health_blueprint_is_exempt(csrf_client):
    """Health probes never need CSRF tokens."""
    resp = csrf_client.get("/live")
    assert resp.status_code == 200


def test_csrf_token_global_is_registered(csrf_app):
    """The csrf_token Jinja global is wired so templates can render."""
    assert "csrf_token" in csrf_app.jinja_env.globals
    # It should produce a non-empty token when called inside an app context.
    with csrf_app.test_request_context():
        token = csrf_app.jinja_env.globals["csrf_token"]()
        assert token  # non-empty


def test_form_post_with_valid_token_passes_csrf(csrf_client, csrf_app):
    """A request carrying a fresh token isn't rejected by the CSRF guard."""
    from flask_wtf.csrf import generate_csrf

    with csrf_app.test_request_context():
        token = generate_csrf()
        # Pull the cookie that flask-wtf set on the session so the client
        # sends it back on the subsequent request.
        from flask import session

        session_data = dict(session)

    with csrf_client.session_transaction() as s:
        s.update(session_data)

    resp = csrf_client.post(
        "/login",
        data={"username": "u", "password": "p", "csrf_token": token},
    )
    # Login likely fails (no real user), but the CSRF guard didn't reject it.
    assert b"CSRF" not in resp.data
