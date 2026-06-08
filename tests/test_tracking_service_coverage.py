"""Tests for tracking_service.py coverage."""

import pytest
from mercury.services.tracking_service import TrackingService


@pytest.fixture
def tracking_service():
    return TrackingService(base_url="http://localhost:5000")


def test_tracking_generate_pixel_url(tracking_service):
    url = tracking_service.generate_tracking_pixel("log123")
    assert "/track/open/log123" in url


def test_tracking_generate_click_url(tracking_service):
    url = tracking_service.wrap_link("http://example.com", "log123")
    assert "/track/click/log123" in url
    assert "url=" in url


def test_tracking_generate_unsubscribe_url(tracking_service, monkeypatch):
    monkeypatch.setenv("TRACKING_BASE_URL", "http://app.com")
    # Refresh base_url if needed or just instantiate with it
    ts = TrackingService(base_url="http://app.com")
    url = ts.generate_unsubscribe_link("log123", "user@test.com")
    assert "http://app.com/track/unsubscribe/log123/" in url


@pytest.mark.asyncio
async def test_tracking_record_open(tracking_service):
    # TrackingService uses in-memory events and record_event
    email_id = tracking_service.generate_email_id("test@test.com")
    event = tracking_service.record_event(email_id, "open", "test@test.com")

    assert event.event_type == "open"
    assert len(tracking_service._events) == 1

    stats = tracking_service.get_email_stats(email_id)
    assert stats["opens"] == 1


@pytest.mark.asyncio
async def test_tracking_record_click(tracking_service):
    email_id = tracking_service.generate_email_id("test@test.com")
    tracking_service.record_event(email_id, "click", "test@test.com", url="http://link.com")

    stats = tracking_service.get_email_stats(email_id)
    assert stats["clicks"] == 1
    assert "http://link.com" in stats["clicked_urls"]


def test_tracking_campaign_stats(tracking_service):
    email_id = tracking_service.generate_email_id("test@test.com", campaign_id="c1")
    tracking_service.record_event(email_id, "open", "test@test.com", metadata={"campaign_id": "c1"})

    stats = tracking_service.get_campaign_stats("c1")
    assert stats["total_emails"] == 1
    assert stats["total_opens"] == 1
    assert stats["open_rate"] == 100.0
