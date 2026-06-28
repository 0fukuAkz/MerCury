"""Regression tests for HTTP security headers, the CSP in particular.

The Content-Security-Policy is the header with the sharpest edge here: a
nonce-based ``script-src`` silently disables ``'unsafe-inline'`` (per the CSP
spec), and a nonce can never apply to inline event-handler *attributes*.
Because every dashboard template wires its controls through inline
``onclick=`` / ``onsubmit=`` handlers, a nonce policy disables every button
in the app with no server error and nothing in the console an operator would
notice — clicks just do nothing. These tests pin a ``script-src`` that keeps
inline handlers working. If you ever want to reintroduce a nonce, migrate the
templates off inline handlers first, then update these tests deliberately.
"""


def _csp(client) -> str:
    # after_request applies the security headers to every response, including
    # the 401 from an unauthenticated /api call — we just need any response.
    resp = client.get("/api/smtp")
    return resp.headers.get("Content-Security-Policy", "")


def _script_src(csp: str) -> str:
    for directive in csp.split(";"):
        directive = directive.strip()
        if directive.startswith("script-src"):
            return directive
    return ""


def test_csp_header_is_present(client):
    assert _csp(client), "Content-Security-Policy header is missing"


def test_script_src_allows_inline_handlers(client):
    """Inline onclick/onsubmit must be permitted, or every button dies."""
    assert "'unsafe-inline'" in _script_src(_csp(client))


def test_script_src_has_no_nonce(client):
    """A nonce would disable 'unsafe-inline' and silently break inline handlers."""
    assert "nonce-" not in _csp(client)


def test_socketio_cdn_is_whitelisted(client):
    """base.html loads the socket.io client from the CDN; it must be allowed."""
    assert "https://cdn.socket.io" in _script_src(_csp(client))


def test_core_security_headers_present(client):
    resp = client.get("/api/smtp")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
