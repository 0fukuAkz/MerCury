"""Tests for the Prometheus /metrics endpoint and HTTP instrumentation.

These run against the conftest ``client`` (the real create_app, which now
calls init_metrics), so they exercise the registered blueprint + the
before/after_request hooks end to end. No login is required for /metrics — the
token gate is its access control.
"""


def test_metrics_endpoint_exposes_prometheus_text(client):
    # One prior request so there is something to count.
    client.get("/live")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "mercury_http_requests_total" in body
    assert "mercury_http_request_duration_seconds" in body
    assert resp.headers["Content-Type"].startswith("text/plain")


def test_metrics_labels_by_route_template_not_concrete_path(client):
    client.get("/live")
    body = client.get("/metrics").get_data(as_text=True)
    # The /live route template appears as an endpoint label value.
    assert 'endpoint="/live"' in body


def test_metrics_token_gate(client, monkeypatch):
    # _authorized() reads the env per-request, so toggling it after app build works.
    monkeypatch.setenv("METRICS_TOKEN", "s3cret")
    assert client.get("/metrics").status_code == 401  # no token
    assert client.get("/metrics?token=nope").status_code == 401  # wrong token
    assert client.get("/metrics?token=s3cret").status_code == 200  # right token (query)
    assert (
        client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    )  # right token (bearer)


def test_metrics_open_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    assert client.get("/metrics").status_code == 200
