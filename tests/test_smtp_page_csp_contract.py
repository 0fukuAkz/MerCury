"""End-to-end CSP / inline-handler contract for the SMTP page.

The "nothing works in the SMTP section" outage was a Content-Security-Policy
that blocked the page's inline ``onclick`` / ``onsubmit`` handlers. The unit
header tests (test_security_headers) prove the *policy* allows inline; this
goes one step further and renders the real ``/smtp`` page through the full
route + template + after_request stack (as a logged-in user) to assert the
two halves actually agree: the page ships inline handlers AND the response
that carries it permits them.

In-process (test_client) on purpose — a true headless-browser click test was
prototyped but a live-server fixture leaked its request-thread DB connection
into other tests; that browser layer is a documented follow-up needing a
browser-enabled CI and a contamination-safe server harness. These assertions
already pin the regression contract.
"""


def _login(client, user):
    """Attach an authenticated Flask-Login session to the test client."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_smtp_page_renders_for_authenticated_user(client, admin_user):
    _login(client, admin_user)
    resp = client.get("/smtp")
    assert resp.status_code == 200


def test_smtp_page_ships_inline_handlers(client, admin_user):
    """The page wires its controls with inline handlers (what the CSP must allow)."""
    _login(client, admin_user)
    html = client.get("/smtp").get_data(as_text=True)
    assert 'onclick="toggleAddPanel()"' in html
    assert "onsubmit=" in html  # the add/edit forms


def test_smtp_page_served_with_inline_permissive_csp(client, admin_user):
    """...and the CSP it is served under permits inline (no nonce that would
    silently disable 'unsafe-inline' and break every button)."""
    _login(client, admin_user)
    csp = client.get("/smtp").headers.get("Content-Security-Policy", "")
    script_src = next((d for d in csp.split(";") if "script-src" in d), "")
    assert "'unsafe-inline'" in script_src
    assert "nonce-" not in csp
