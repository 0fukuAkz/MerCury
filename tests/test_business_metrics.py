"""Tests for the send-pipeline business metrics (utils/metrics.py).

Counters live on the process-global default registry, so assertions use
before/after deltas rather than absolute values.
"""

from prometheus_client import REGISTRY

from mercury.utils import metrics


def _val(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_record_send_result_counts_sent_and_failed():
    before_sent = _val("mercury_emails_sent_total")
    before_fail = _val("mercury_emails_failed_total", {"type": "permanent"})
    metrics.record_send_result(True)
    metrics.record_send_result(False, "permanent")
    assert _val("mercury_emails_sent_total") == before_sent + 1
    assert _val("mercury_emails_failed_total", {"type": "permanent"}) == before_fail + 1


def test_failed_unknown_type_buckets_as_other():
    """An unexpected error_type must not explode label cardinality."""
    before = _val("mercury_emails_failed_total", {"type": "other"})
    metrics.record_send_result(False, "smtp-555-some-weird-string")
    assert _val("mercury_emails_failed_total", {"type": "other"}) == before + 1


def test_campaign_gauge_inc_then_dec():
    before = _val("mercury_campaigns_active")
    metrics.campaign_started()
    assert _val("mercury_campaigns_active") == before + 1
    metrics.campaign_finished()
    assert _val("mercury_campaigns_active") == before


def test_business_metrics_exposed_on_metrics_endpoint(client):
    metrics.record_send_result(True)
    metrics.campaign_started()
    metrics.campaign_finished()
    body = client.get("/metrics").get_data(as_text=True)
    assert "mercury_emails_sent_total" in body
    assert "mercury_campaigns_active" in body
