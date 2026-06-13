"""Tests for Campaigns API routes."""

import pytest
import json
from unittest.mock import patch, MagicMock
from mercury.data.models import Attachment, SMTPServer, Template
from mercury.data.models.campaign import Campaign, CampaignStatus


def test_api_list_campaigns(client, auth_headers, db_session):
    c = Campaign(name="Camp1", status=CampaignStatus.DRAFT)
    db_session.add(c)
    db_session.commit()

    response = client.get("/api/campaigns", headers=auth_headers)
    assert response.status_code == 200
    res = response.get_json()
    assert "campaigns" in res
    assert len(res["campaigns"]) > 0


def test_api_create_campaign_invalid(client, auth_headers):
    response = client.post("/api/campaigns", headers=auth_headers, json={})
    assert response.status_code == 400
    assert "Campaign name required" in response.get_json()["error"]


def test_api_create_campaign_logo_validation(client, auth_headers, db_session):
    # 1. Non-existent logo ID
    response = client.post(
        "/api/campaigns",
        headers=auth_headers,
        json={"name": "Test Campaign", "logo_attachment_id": "9999"},
    )
    assert response.status_code == 400
    assert "logo_attachment_id=9999 not found" in response.get_json()["error"]

    # 2. Logo ID exists but is inactive
    att_inactive = Attachment(
        filename="logo_inactive.png",
        stored_name="logo_inactive.png",
        size_bytes=100,
        content_type="image/png",
        is_active=False,
    )
    db_session.add(att_inactive)
    db_session.commit()

    response = client.post(
        "/api/campaigns",
        headers=auth_headers,
        json={"name": "Test Campaign", "logo_attachment_id": str(att_inactive.id)},
    )
    assert response.status_code == 400
    assert f"logo_attachment_id={att_inactive.id} not found" in response.get_json()["error"]

    # 3. Logo ID exists, active, but wrong content type
    att_txt = Attachment(
        filename="not_image.txt",
        stored_name="not_image.txt",
        size_bytes=100,
        content_type="text/plain",
        is_active=True,
    )
    db_session.add(att_txt)
    db_session.commit()

    response = client.post(
        "/api/campaigns",
        headers=auth_headers,
        json={"name": "Test Campaign", "logo_attachment_id": str(att_txt.id)},
    )
    assert response.status_code == 400
    assert "Logo must be an image file" in response.get_json()["error"]

    # 4. Valid logo ID
    att_img = Attachment(
        filename="logo.png",
        stored_name="logo.png",
        size_bytes=100,
        content_type="image/png",
        is_active=True,
    )
    db_session.add(att_img)
    db_session.commit()

    with patch("mercury.services.campaign_service.CampaignService.create_campaign") as mock_create:
        mock_camp = MagicMock()
        mock_camp.id = 1
        mock_camp.to_dict.return_value = {"id": 1, "name": "Test Campaign"}
        mock_create.return_value = mock_camp

        response = client.post(
            "/api/campaigns",
            headers=auth_headers,
            json={"name": "Test Campaign", "logo_attachment_id": str(att_img.id)},
        )
        assert response.status_code == 200
        assert response.get_json()["success"] is True


def test_api_create_campaign_smtp_parsing(client, auth_headers):
    # Test valid numeric string, invalid non-numeric, null/empty SMTP server ID
    mock_camp = MagicMock()
    mock_camp.id = 1
    mock_camp.to_dict.return_value = {"id": 1, "name": "Test Campaign"}

    with patch("mercury.services.campaign_service.CampaignService.create_campaign", return_value=mock_camp):
        # Numeric string
        response = client.post(
            "/api/campaigns",
            headers=auth_headers,
            json={"name": "Test Campaign", "smtp_server_id": "123"},
        )
        assert response.status_code == 200

        # Non-numeric string (coerced to None)
        response = client.post(
            "/api/campaigns",
            headers=auth_headers,
            json={"name": "Test Campaign", "smtp_server_id": "abc"},
        )
        assert response.status_code == 200

        # "null" / empty string (coerced to None)
        response = client.post(
            "/api/campaigns",
            headers=auth_headers,
            json={"name": "Test Campaign", "smtp_server_id": "null"},
        )
        assert response.status_code == 200


def test_api_get_campaign_not_found(client, auth_headers):
    response = client.get("/api/campaigns/99999", headers=auth_headers)
    assert response.status_code == 404
    assert response.get_json()["error"] == "Campaign not found"


def test_api_get_campaign_success(client, auth_headers, db_session):
    c = Campaign(name="Get Camp", status=CampaignStatus.DRAFT)
    db_session.add(c)
    db_session.commit()

    response = client.get(f"/api/campaigns/{c.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["campaign"]["name"] == "Get Camp"


def test_api_update_campaign_not_found(client, auth_headers):
    response = client.put("/api/campaigns/99999", headers=auth_headers, json={"name": "New Name"})
    assert response.status_code == 404
    assert response.get_json()["error"] == "Campaign not found"


def test_api_update_campaign_wrong_status(client, auth_headers, db_session):
    c = Campaign(name="Active Camp", status=CampaignStatus.SENDING)
    db_session.add(c)
    db_session.commit()

    response = client.put(f"/api/campaigns/{c.id}", headers=auth_headers, json={"name": "New Name"})
    assert response.status_code == 400
    assert "Only draft or scheduled campaigns can be edited" in response.get_json()["error"]


def test_api_update_campaign_success(client, auth_headers, db_session):
    # Create valid references in DB to avoid FK constraint failures
    tmpl = Template(name="Tmpl", subject="Sub", html_content="Content")
    logo_att = Attachment(
        filename="l.png", stored_name="l.png", size_bytes=10, content_type="image/png", is_active=True
    )
    db_session.add_all([tmpl, logo_att])
    db_session.commit()

    c = Campaign(name="Draft Camp", status=CampaignStatus.DRAFT, settings={})
    db_session.add(c)
    db_session.commit()

    update_payload = {
        "name": "Updated draft camp",
        "description": "New description",
        "template_id": str(tmpl.id),
        "send_as_image": True,
        "subjects": ["Subject A", "Subject B"],
        "manual_recipients": [{"email": "rec@example.com"}],
        "links": ["http://a.com", "http://b.com"],
        "recipients_path": "/path/rec.csv",
        "dry_run": False,
        "from_emails": ["a@ex.com"],
        "from_names": ["Sender A"],
        "template_path": "/path/temp.html",
        "templates": [{"name": "T1"}],
        "enable_tracking": False,
        "track_opens": False,
        "track_clicks": False,
        "tracking_base_url": "http://track.me",
        "smtp_server_id": "42",
        "convert_attachment": True,
        "auto_company_logo": True,
        "hide_from_email_header": True,
        "include_default_body": True,
        "validate_emails": False,
        "deduplicate": False,
        "attachment_convert_to": "pdf",
        "placeholders_path": "/path/placeholders.json",
        "mail_priority": "1",
        "attachment_ids": ["10", "abc", "20"],
        "logo_attachment_id": str(logo_att.id),
    }

    response = client.put(f"/api/campaigns/{c.id}", headers=auth_headers, json=update_payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["campaign"]["name"] == "Updated draft camp"

    # Fetch fresh from DB to verify persistence
    db_session.expire_all()
    fresh = db_session.query(Campaign).get(c.id)
    assert fresh.name == "Updated draft camp"
    assert fresh.description == "New description"
    assert fresh.template_id == tmpl.id
    assert fresh.convert_to_image is True
    assert fresh.subjects == ["Subject A", "Subject B"]
    assert fresh.settings["manual_recipients"] == [{"email": "rec@example.com"}]
    assert fresh.settings["links"] == ["http://a.com", "http://b.com"]
    assert fresh.settings["recipients_path"] == "/path/rec.csv"
    assert fresh.settings["dry_run"] is False
    assert fresh.settings["from_emails"] == ["a@ex.com"]
    assert fresh.settings["from_names"] == ["Sender A"]
    assert fresh.settings["template_path"] == "/path/temp.html"
    assert fresh.settings["templates"] == [{"name": "T1"}]
    assert fresh.settings["enable_tracking"] is False
    assert fresh.settings["track_opens"] is False
    assert fresh.settings["track_clicks"] is False
    assert fresh.settings["tracking_base_url"] == "http://track.me"
    assert fresh.settings["smtp_server_id"] == 42
    assert fresh.settings["convert_attachment"] is True
    assert fresh.settings["auto_company_logo"] is True
    assert fresh.settings["hide_from_email_header"] is True
    assert fresh.settings["include_default_body"] is True
    assert fresh.settings["validate_emails"] is False
    assert fresh.settings["deduplicate"] is False
    assert fresh.settings["attachment_convert_to"] == "pdf"
    assert fresh.settings["placeholders_path"] == "/path/placeholders.json"
    assert fresh.settings["mail_priority"] == "1"
    assert fresh.settings["attachment_ids"] == [10, 20]
    assert fresh.settings["logo_attachment_id"] == logo_att.id


def test_api_update_campaign_subject_string(client, auth_headers, db_session):
    c = Campaign(name="Draft Camp 3", status=CampaignStatus.DRAFT, settings={})
    db_session.add(c)
    db_session.commit()

    update_payload = {
        "subject": "Single Subject String",
    }
    response = client.put(f"/api/campaigns/{c.id}", headers=auth_headers, json=update_payload)
    assert response.status_code == 200
    db_session.expire_all()
    fresh = db_session.query(Campaign).get(c.id)
    assert fresh.subjects == ["Single Subject String"]


def test_api_update_campaign_coercion_edge_cases(client, auth_headers, db_session):
    c = Campaign(name="Draft Camp 2", status=CampaignStatus.DRAFT, settings={})
    db_session.add(c)
    db_session.commit()

    # Pass non-int/empty/null fields for smtp_server_id and template_id to check coercion
    update_payload = {
        "smtp_server_id": "not-int",
        "logo_attachment_id": "not-int",
        "template_id": "null",
    }
    response = client.put(f"/api/campaigns/{c.id}", headers=auth_headers, json=update_payload)
    assert response.status_code == 200
    db_session.expire_all()
    fresh = db_session.query(Campaign).get(c.id)
    assert fresh.template_id is None
    assert fresh.settings["smtp_server_id"] is None
    assert fresh.settings["logo_attachment_id"] is None


def test_api_update_campaign_null_coercion(client, auth_headers, db_session):
    c = Campaign(name="Draft Camp 4", status=CampaignStatus.DRAFT, settings={})
    db_session.add(c)
    db_session.commit()

    # Pass 0/"0"/"null"/empty values to check null settings coercion
    update_payload = {
        "smtp_server_id": "0",
        "logo_attachment_id": "null",
    }
    response = client.put(f"/api/campaigns/{c.id}", headers=auth_headers, json=update_payload)
    assert response.status_code == 200
    db_session.expire_all()
    fresh = db_session.query(Campaign).get(c.id)
    assert fresh.settings["smtp_server_id"] is None
    assert fresh.settings["logo_attachment_id"] is None


def test_api_delete_campaign(client, auth_headers, db_session):
    c = Campaign(name="To Delete", status=CampaignStatus.SENDING)
    db_session.add(c)
    db_session.commit()

    campaign_id = c.id
    mock_svc = MagicMock()
    active_services = {campaign_id: mock_svc}

    with patch("mercury.web.events._active_services", active_services):
        response = client.delete(f"/api/campaigns/{campaign_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["success"] is True

    mock_svc.stop.assert_called_once()
    db_session.expire_all()
    fresh = db_session.query(campaign_id)  # Wait, database.get works or query(Campaign).get? query(Campaign).get is standard
    fresh = db_session.query(Campaign).get(campaign_id)
    assert fresh is None  # Check deleted from DB


def test_api_delete_campaign_not_found(client, auth_headers):
    response = client.delete("/api/campaigns/99999", headers=auth_headers)
    assert response.status_code == 404
    assert response.get_json()["error"] == "Campaign not found"


def test_api_bulk_delete_campaigns_invalid_payload(client, auth_headers):
    response = client.post("/api/campaigns/bulk-delete", headers=auth_headers, json={})
    assert response.status_code == 400
    assert "List of campaign IDs required" in response.get_json()["error"]


def test_api_bulk_delete_campaigns(client, auth_headers, db_session):
    c1 = Campaign(name="C1", status=CampaignStatus.SENDING)
    c2 = Campaign(name="C2", status=CampaignStatus.DRAFT)
    db_session.add_all([c1, c2])
    db_session.commit()

    c1_id = c1.id
    c2_id = c2.id

    mock_svc1 = MagicMock()
    active_services = {c1_id: mock_svc1}

    with patch("mercury.web.events._active_services", active_services):
        response = client.post(
            "/api/campaigns/bulk-delete",
            headers=auth_headers,
            json={"ids": [c1_id, c2_id, 99999]},
        )
        assert response.status_code == 200
        res = response.get_json()
        assert res["success"] is True
        assert res["deleted"] == 2
        assert res["not_found"] == [99999]

    mock_svc1.stop.assert_called_once()
    db_session.expire_all()
    assert db_session.query(Campaign).get(c1_id) is None
    assert db_session.query(Campaign).get(c2_id) is None


def test_api_clone_campaign(client, auth_headers, db_session):
    c = Campaign(
        name="Orig",
        description="Desc",
        status=CampaignStatus.SENDING,
        from_emails=["a@b.com"],
        from_names=["Name"],
        settings={"dry_run": True},
    )
    db_session.add(c)
    db_session.commit()

    response = client.post(f"/api/campaigns/{c.id}/clone", headers=auth_headers)
    assert response.status_code == 200
    res = response.get_json()
    assert res["success"] is True
    assert res["campaign"]["name"] == "Orig (Copy)"
    assert res["campaign"]["status"] == "draft"
    assert res["campaign"]["from_emails"] == ["a@b.com"]
    assert res["campaign"]["settings"]["dry_run"] is True


def test_api_clone_campaign_not_found(client, auth_headers):
    response = client.post("/api/campaigns/99999/clone", headers=auth_headers)
    assert response.status_code == 404


def test_api_campaign_engagement_stats(client, auth_headers):
    with patch(
        "mercury.data.repositories.LogRepository.get_campaign_engagement_stats"
    ) as mock_stats:
        mock_stats.return_value = {"opens": 10}
        response = client.get("/api/campaigns/1/stats/engagement", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"opens": 10}


def test_api_campaign_smtp_stats(client, auth_headers):
    with patch(
        "mercury.data.repositories.LogRepository.get_smtp_performance_stats"
    ) as mock_stats:
        mock_stats.return_value = [{"server": "s1", "sent": 5}]
        response = client.get("/api/campaigns/1/stats/smtp", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"servers": [{"server": "s1", "sent": 5}]}


def test_api_campaign_geo_stats(client, auth_headers):
    with patch("mercury.data.repositories.LogRepository.get_campaign_geo_stats") as mock_stats:
        mock_stats.return_value = [{"country": "US", "count": 3}]
        response = client.get("/api/campaigns/1/stats/geo", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == {"geo": [{"country": "US", "count": 3}]}


def test_api_campaign_timeline_stats(client, auth_headers):
    with patch(
        "mercury.data.repositories.LogRepository.get_campaign_timeline_stats"
    ) as mock_stats:
        mock_stats.return_value = [{"time": "12:00", "sent": 2}]
        response = client.get("/api/campaigns/1/stats/timeline", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json() == [{"time": "12:00", "sent": 2}]
