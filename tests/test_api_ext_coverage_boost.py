"""Extended API testing module to massively boost coverage of campaigns lifecycle, testing, placeholders and dead letters."""

import json
from unittest.mock import patch, MagicMock, AsyncMock

from mercury.data.models import (
    Campaign,
    CampaignStatus,
    SMTPServer,
    Template,
    Attachment,
    CustomPlaceholder,
    DeadLetter,
)


# --- CAMPAIGNS TESTING MODULE TESTS (/api/campaigns/test-email) ---


def test_api_send_test_email_missing_recipient(client, auth_headers):
    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": ""},
    )
    assert response.status_code == 400
    data = json.loads(response.data)
    assert "required" in data["error"]


def test_api_send_test_email_invalid_logo(client, auth_headers, db_session):
    # Test non-existent logo digital ID
    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": "aa@bb.com", "logo_attachment_id": "99999"},
    )
    assert response.status_code == 400
    assert "not found in library" in json.loads(response.data)["error"]

    # Test inactive logo attachment
    logo = Attachment(
        filename="logo.bin", stored_name="logo1.bin", is_active=False, content_type="image/png"
    )
    db_session.add(logo)
    db_session.commit()
    logo_id = logo.id

    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": "aa@bb.com", "logo_attachment_id": str(logo_id)},
    )
    assert response.status_code == 400
    assert "not found in library" in json.loads(response.data)["error"]

    # Test logo non-image mime-type
    logo2 = Attachment(
        filename="logo.bin",
        stored_name="logo2.bin",
        is_active=True,
        content_type="application/octet-stream",
    )
    db_session.add(logo2)
    db_session.commit()
    logo_id2 = logo2.id

    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": "aa@bb.com", "logo_attachment_id": str(logo_id2)},
    )
    assert response.status_code == 400
    assert "Logo must be an image file" in json.loads(response.data)["error"]


def test_api_send_test_email_no_active_smtp_servers(client, auth_headers, db_session):
    # No server is enabled
    db_session.query(SMTPServer).delete()
    db_session.commit()

    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": "aa@bb.com"},
    )
    assert response.status_code == 400
    assert "No active SMTP servers configured" in json.loads(response.data)["error"]


def test_api_send_test_email_pinned_smtp_missing_or_disabled(client, auth_headers, db_session):
    # Try looking for pinned disabled/missing server
    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": "aa@bb.com", "smtp_server_id": "8888"},
    )
    assert response.status_code == 400
    assert "Pinned SMTP server id=8888 is missing or disabled" in json.loads(response.data)["error"]


def test_api_send_test_email_fallback_checks(client, auth_headers, db_session):
    # Configure a server without defaults
    db_session.query(SMTPServer).delete()
    server = SMTPServer(
        name="DefaultServer",
        host="smtp.test.com",
        is_enabled=True,
        from_email="",  # empty
    )
    db_session.add(server)
    db_session.commit()

    # Should report "From Email is required. Provide it in the form..."
    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={"test_recipient": "aa@bb.com"},
    )
    assert response.status_code == 400
    assert "From Email is required" in json.loads(response.data)["error"]


@patch("mercury.services.email.EmailService")
def test_api_send_test_email_success_with_template_and_tracking(
    mock_email_service_class, client, auth_headers, db_session, tmp_path
):
    # Configure enabled SMTP server
    db_session.query(SMTPServer).delete()
    server = SMTPServer(
        name="SMTP-Default",
        host="smtp.test.com",
        is_enabled=True,
        from_email="sender_default@test.com",
        from_name="Default Sender",
    )
    db_session.add(server)

    # Configure template
    tpl = Template(
        name="T1", subject="Subject Template", html_content="Content template with {{qr_code}}"
    )
    db_session.add(tpl)
    db_session.commit()

    # Mock the email service sending result
    mock_email_service = MagicMock()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.correlation_id = "corr-1122"
    mock_result.smtp_server = "smtp.test.com"
    mock_result.smtp_response = "250 Delivered"
    mock_email_service.send_single = AsyncMock(return_value=mock_result)
    mock_email_service_class.return_value = mock_email_service

    # Send with template_id
    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={
            "test_recipient": "john@example.com",
            "template_id": str(tpl.id),
            "enable_tracking": "on",
            "track_opens": "1",
            "track_clicks": "true",
            "enable_qr_code": "on",
            "logo_attachment_id": "",
        },
    )
    assert response.status_code == 200, f"Error is: {response.data.decode()}"
    res_data = json.loads(response.data)
    assert res_data["success"] is True
    assert res_data["correlation_id"] == "corr-1122"

    # Send with file path templates
    temp_tpl = tmp_path / "test_tpl.html"
    temp_tpl.write_text("Hello from custom file path body!")

    with patch("os.getcwd", return_value=str(tmp_path)):
        response = client.post(
            "/api/campaigns/test-email",
            headers=auth_headers,
            json={
                "test_recipient": "john@example.com",
                "template_path": str(temp_tpl),
                "from_email": "sender_default@test.com",
            },
        )
    assert response.status_code == 200, f"Error is: {response.data.decode()}"


def test_api_send_test_email_from_ownership_validation_failure(client, auth_headers, db_session):
    # Clear and configure an SMTP server with from_email defined
    db_session.query(SMTPServer).delete()
    server1 = SMTPServer(
        name="Authorised-One",
        host="smtp.one.com",
        is_enabled=True,
        from_email="authorized_sender@one.com",
    )
    db_session.add(server1)
    db_session.commit()

    # Send using an unauthorised email address, verify Form ownership validation blocks it
    response = client.post(
        "/api/campaigns/test-email",
        headers=auth_headers,
        json={
            "test_recipient": "recipient@example.com",
            "from_email": "unauthorised_sender@two.com",
        },
    )
    assert response.status_code == 400
    assert "is not authorized on any configured SMTP server" in json.loads(response.data)["error"]


# --- CAMPAIGNS LIFECYCLE TESTS (/api/campaigns/<id>/start) ---


def test_api_start_campaign_not_found(client, auth_headers):
    response = client.post("/api/campaigns/99999/start", headers=auth_headers)
    assert response.status_code == 404
    assert "not found" in json.loads(response.data)["error"].lower()


def test_api_start_campaign_already_running(client, auth_headers):
    from mercury.web.events import _active_services

    _active_services[123] = "dummy_service"
    try:
        response = client.post("/api/campaigns/123/start", headers=auth_headers)
        assert response.status_code == 409
        assert "Campaign already running" in json.loads(response.data)["error"]
    finally:
        _active_services.pop(123, None)


def test_api_start_campaign_invalid_status(client, auth_headers, db_session):
    # Campaign is completed
    campaign = Campaign(name="Done Campaign", status=CampaignStatus.COMPLETED)
    db_session.add(campaign)
    db_session.commit()
    camp_id = campaign.id

    response = client.post(f"/api/campaigns/{camp_id}/start", headers=auth_headers)
    assert response.status_code == 400
    assert "Cannot start campaign with status" in json.loads(response.data)["error"]


@patch("threading.Thread")
def test_api_start_campaign_success(mock_thread, client, auth_headers, db_session):
    campaign = Campaign(name="Draft Campaign", status=CampaignStatus.DRAFT)
    db_session.add(campaign)
    db_session.commit()
    camp_id = campaign.id

    response = client.post(f"/api/campaigns/{camp_id}/start", headers=auth_headers)
    assert response.status_code == 200
    res_data = json.loads(response.data)
    assert res_data["success"] is True
    assert res_data["campaign_id"] == camp_id
    assert res_data["status"] == "starting"
    assert mock_thread.called


# --- CUSTOM PLACEHOLDERS TESTS (/api/placeholders) ---


def test_api_placeholders_catalog(client, auth_headers, db_session):
    # Insert custom placeholder
    cp = CustomPlaceholder(
        name="custom.test", value="CustomVal", description="Custom Desc", is_active=True
    )
    db_session.add(cp)
    db_session.commit()

    response = client.get("/api/placeholders", headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "builtins" in data
    assert "custom" in data
    assert any(c["name"] == "custom.test" for c in data["custom"])


def test_api_list_custom_placeholders(client, auth_headers):
    response = client.get("/api/placeholders/custom", headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert "custom" in data


def test_api_create_custom_placeholder_validations(client, auth_headers, db_session):
    db_session.query(CustomPlaceholder).delete()
    db_session.commit()

    # Empty name
    response = client.post("/api/placeholders/custom", headers=auth_headers, json={"name": ""})
    assert response.status_code == 400
    assert "name is required" in json.loads(response.data)["error"]

    # Invalid characters in name
    response = client.post(
        "/api/placeholders/custom", headers=auth_headers, json={"name": "CapitalLetter!"}
    )
    assert response.status_code == 400
    assert "name must start with" in json.loads(response.data)["error"]

    # Valid creation
    response = client.post(
        "/api/placeholders/custom",
        headers=auth_headers,
        json={"name": "my_new_placeholder", "value": "Val123", "description": "Desc"},
    )
    assert response.status_code == 201
    assert json.loads(response.data)["success"] is True

    # Duplicate creation error (conflict)
    response = client.post(
        "/api/placeholders/custom",
        headers=auth_headers,
        json={"name": "my_new_placeholder", "value": "DifferentVal"},
    )
    assert response.status_code == 409
    assert "already exists" in json.loads(response.data)["error"]


def test_api_update_custom_placeholder(client, auth_headers, db_session):
    cp = CustomPlaceholder(
        name="update_target", value="OldVal", description="Old Desc", is_active=True
    )
    cp2 = CustomPlaceholder(name="clashing_placeholder", value="SomeVal")
    db_session.add_all([cp, cp2])
    db_session.commit()
    cp_id = cp.id

    # Not found update
    response = client.put("/api/placeholders/custom/99999", headers=auth_headers, json={})
    assert response.status_code == 404

    # Invalid name format update
    response = client.put(
        f"/api/placeholders/custom/{cp_id}", headers=auth_headers, json={"name": "BAD!"}
    )
    assert response.status_code == 400

    # Pinned uniqueness clashes on update
    response = client.put(
        f"/api/placeholders/custom/{cp_id}",
        headers=auth_headers,
        json={"name": "clashing_placeholder"},
    )
    assert response.status_code == 409

    # Successful update
    response = client.put(
        f"/api/placeholders/custom/{cp_id}",
        headers=auth_headers,
        json={
            "name": "update_target_updated",
            "value": "NewVal",
            "description": "New Desc",
            "is_active": False,
        },
    )
    assert response.status_code == 200
    res_data = json.loads(response.data)
    assert res_data["success"] is True
    assert res_data["placeholder"]["name"] == "update_target_updated"
    assert res_data["placeholder"]["value"] == "NewVal"
    assert res_data["placeholder"]["is_active"] is False


def test_api_delete_custom_placeholder(client, auth_headers, db_session):
    cp = CustomPlaceholder(name="delete_target", value="Val")
    db_session.add(cp)
    db_session.commit()
    cp_id = cp.id

    # Not found delete
    response = client.delete("/api/placeholders/custom/99999", headers=auth_headers)
    assert response.status_code == 404

    # Successful delete
    response = client.delete(f"/api/placeholders/custom/{cp_id}", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is True


# --- DEAD LETTER API REQUEUE & REQUEUE-ALL TESTS ---


def test_api_dead_letter_list_and_discard_all(client, auth_headers, db_session):
    db_session.query(DeadLetter).delete()
    item = DeadLetter(
        recipient="failed_one@test.com",
        subject="Fail Subject",
        html_body="Fail html body",
        from_email="sender@demo.com",
        error_type="connection_error",
        error_message="Timeout during connection",
    )
    db_session.add(item)
    db_session.commit()

    # List
    response = client.get("/api/dead-letter", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["count"] == 1

    # Discard non-existent
    resp_del_miss = client.delete("/api/dead-letter/99999", headers=auth_headers)
    assert resp_del_miss.status_code == 200
    assert json.loads(resp_del_miss.data)["success"] is False

    # Discard specific
    resp_del = client.delete(f"/api/dead-letter/{item.id}", headers=auth_headers)
    assert resp_del.status_code == 200

    # Add duplicate and bulk-discard
    item2 = DeadLetter(
        recipient="failed_two@test.com",
        subject="sub",
        html_body="body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        resolved=False,
    )
    db_session.add(item2)
    db_session.commit()

    resp_discard_all = client.post("/api/dead-letter/discard-all", headers=auth_headers)
    assert resp_discard_all.status_code == 200
    assert json.loads(resp_discard_all.data)["discarded"] == 1


def test_requeue_dead_letter_not_found(client, auth_headers):
    # test 404 Not Found outcome
    response = client.post("/api/dead-letter/99999/requeue", headers=auth_headers)
    assert response.status_code == 404


def test_requeue_dead_letter_already_resolved(client, auth_headers, db_session):
    # resolved=True
    item = DeadLetter(
        recipient="already_done@test.com",
        subject="sub",
        html_body="body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        resolved=True,
    )
    db_session.add(item)
    db_session.commit()

    response = client.post(f"/api/dead-letter/{item.id}/requeue", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is False
    assert "already resolved" in json.loads(response.data)["error"]


def test_requeue_dead_letter_no_smtp_servers(client, auth_headers, db_session):
    # Clear SMTPServers in DB
    db_session.query(SMTPServer).delete()
    item = DeadLetter(
        recipient="unrequeued@test.com",
        subject="sub",
        html_body="body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        resolved=False,
    )
    db_session.add(item)
    db_session.commit()

    response = client.post(f"/api/dead-letter/{item.id}/requeue", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is False
    assert "No active SMTP servers configured" in json.loads(response.data)["error"]


def test_requeue_dead_letter_missing_default_from_email_checks(client, auth_headers, db_session):
    # Insert server with empty default Sender
    db_session.query(SMTPServer).delete()
    server = SMTPServer(
        name="SenderlessSmtp", host="smtp.empty.com", is_enabled=True, from_email=""
    )
    db_session.add(server)

    item = DeadLetter(
        recipient="failed-address@test.com",
        subject="sub",
        html_body="body",
        from_email="",
        error_type="type",
        error_message="msg",
        resolved=False,
    )
    db_session.add(item)
    db_session.commit()

    response = client.post(f"/api/dead-letter/{item.id}/requeue", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is False
    assert "no from_email and no SMTP server default" in json.loads(response.data)["error"]


@patch("mercury.web.routes.api.dead_letter.run_async")
def test_requeue_dead_letter_success_and_failures(mock_run_async, client, auth_headers, db_session):
    db_session.query(SMTPServer).delete()
    server = SMTPServer(
        name="TestSmtp", host="smtp.test.com", is_enabled=True, from_email="def_send@test.com"
    )
    db_session.add(server)

    item1 = DeadLetter(
        recipient="success_requeue@test.com",
        subject="Sub",
        html_body="Body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        resolved=False,
    )
    item2 = DeadLetter(
        recipient="failed_requeue@test.com",
        subject="Sub",
        html_body="Body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        resolved=False,
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    # Success mock
    mock_res_success = MagicMock()
    mock_res_success.success = True
    mock_res_success.smtp_server = "smtp.test.com"
    mock_res_success.smtp_response = "250 OK"

    # Fail mock
    mock_res_fail = MagicMock()
    mock_res_fail.success = False
    mock_res_fail.smtp_server = "smtp.test.com"
    mock_res_fail.error = "Auth Failure"

    mock_run_async.side_effect = [mock_res_success, mock_res_fail]

    # Test success requeue
    response = client.post(f"/api/dead-letter/{item1.id}/requeue", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is True

    # Test fail requeue
    response = client.post(f"/api/dead-letter/{item2.id}/requeue", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is False


def test_requeue_all_empty(client, auth_headers, db_session):
    db_session.query(DeadLetter).delete()
    db_session.commit()

    response = client.post("/api/dead-letter/requeue-all", headers=auth_headers)
    assert response.status_code == 200
    assert json.loads(response.data)["success"] is False
    assert "No pending messages to requeue" in json.loads(response.data)["error"]


def test_requeue_all_creates_new_campaign_blank_and_recovery(client, auth_headers, db_session):
    db_session.query(DeadLetter).delete()
    db_session.query(Campaign).delete()

    item1 = DeadLetter(
        recipient="dl_rec1@test.com",
        subject="sub",
        html_body="body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        resolved=False,
    )
    db_session.add(item1)
    db_session.commit()

    # Case 1: Requeue all when no source campaign matches (generates blank "Dead Letter Recovery")
    response = client.post("/api/dead-letter/requeue-all", headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["success"] is True
    assert "recovery campaign" in data["message"].lower()

    # Case 2: Requeue all cloning from a linked source campaign
    # Insert source campaign
    src_camp = Campaign(
        name="Source Campaign",
        subjects=["Subject Rotated"],
        concurrency=10,
        rate_per_minute=200,
        status=CampaignStatus.COMPLETED,
    )
    db_session.add(src_camp)
    db_session.commit()
    src_camp_id = src_camp.id

    # Re-open unresolved item
    item2 = DeadLetter(
        recipient="dl_rec2@test.com",
        subject="sub",
        html_body="body",
        from_email="sender@demo.com",
        error_type="type",
        error_message="msg",
        campaign_id=src_camp_id,
        resolved=False,
    )
    db_session.add(item2)
    db_session.commit()

    response = client.post("/api/dead-letter/requeue-all", headers=auth_headers)
    assert response.status_code == 200
    data2 = json.loads(response.data)
    assert data2["success"] is True
    assert "recovery campaign" in data2["message"].lower()

    # Validate that draft campaign was created with correct settings
    db_session.expire_all()
    created = (
        db_session.query(Campaign).filter(Campaign.name.like("%(Dead Letter Recovery)%")).first()
    )
    assert created is not None
    assert created.status == CampaignStatus.DRAFT
    assert created.concurrency == 10
    assert "dl_rec2@test.com" in created.settings["filter_emails"]
