import pytest
from unittest.mock import patch, ANY


@pytest.fixture
def mock_tracking_service():
    with patch("mercury.web.routes.tracking.TrackingService") as MockService:
        yield MockService.return_value


class TestTrackingRoutes:
    def test_track_open(self, client, mock_tracking_service):
        resp = client.get("/track/open/123")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"] == "image/gif"
        mock_tracking_service.record_event.assert_called_with(
            email_id="123", event_type="open", recipient="", ip_address=ANY, user_agent=ANY
        )

    def test_track_click(self, client, mock_tracking_service):
        target_url = "http://example.com"
        resp = client.get(f"/track/click/123?url={target_url}&lid=link1")
        assert resp.status_code == 302
        assert resp.location == target_url
        mock_tracking_service.record_event.assert_called_with(
            email_id="123",
            event_type="click",
            recipient="",
            ip_address=ANY,
            user_agent=ANY,
            metadata={"url": target_url, "link_id": "link1"},
        )

    def test_track_click_default_url(self, client, mock_tracking_service):
        resp = client.get("/track/click/123")
        assert resp.status_code == 302
        assert resp.location == "/" or resp.location.endswith("/")  # relative or absolute

    def test_unsubscribe_valid(self, client, mock_tracking_service):
        with patch("mercury.security.auth.validate_unsubscribe_token", return_value=(True, "")):
            resp = client.get("/track/unsubscribe/123/valid_token")
            assert resp.status_code == 200
            assert b"unsubscribed successfully" in resp.data
            mock_tracking_service.record_event.assert_called()

    def test_unsubscribe_invalid(self, client, mock_tracking_service):
        with patch("mercury.security.auth.validate_unsubscribe_token", return_value=(False, "Invalid")):
            resp = client.get("/track/unsubscribe/123/invalid_token")
            assert resp.status_code == 403
            assert b"Invalid unsubscribe token" in resp.data
