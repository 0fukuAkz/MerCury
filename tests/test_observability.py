"""Tests for the optional Sentry wiring in web/observability.py.

We never hit the network: ``sentry_sdk.init`` is mocked. The contract under
test is the *policy* around it — activate only with a DSN, keep PII off, and
never let an SDK failure propagate into app boot.
"""

from unittest.mock import patch

from mercury.web import observability


def test_init_sentry_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observability.init_sentry() is False


def test_init_sentry_activates_with_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://abc@example.ingest.sentry.io/1")
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

    with patch("sentry_sdk.init") as mock_init:
        assert observability.init_sentry() is True
        assert mock_init.call_count == 1
        kwargs = mock_init.call_args.kwargs
        # PII must stay off by default — recipient data must never leak.
        assert kwargs["send_default_pii"] is False
        assert kwargs["environment"] == "production"
        # Errors-only by default (no perf tracing unless opted in).
        assert kwargs["traces_sample_rate"] == 0.0


def test_init_sentry_honours_traces_sample_rate(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://abc@example.ingest.sentry.io/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")
    with patch("sentry_sdk.init") as mock_init:
        observability.init_sentry()
        assert mock_init.call_args.kwargs["traces_sample_rate"] == 0.25


def test_init_sentry_never_raises_on_init_failure(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://abc@example.ingest.sentry.io/1")
    with patch("sentry_sdk.init", side_effect=RuntimeError("boom")):
        # An SDK-internal failure must be swallowed, not propagated to boot.
        assert observability.init_sentry() is False


def test_detect_release_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("MERCURY_RELEASE", "v9.9.9-test")
    assert observability._detect_release() == "v9.9.9-test"
