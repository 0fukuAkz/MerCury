"""Tests for SMTP API routes."""

import pytest
import json
from unittest.mock import patch, MagicMock
from mercury.data.models import SMTPServer, EmailLog, EmailStatus
from mercury.web.routes.api.smtp import _validate_smtp_payload


def test_validate_smtp_payload():
    # TLS mode validation
    assert _validate_smtp_payload({"tls_mode": "invalid"}, partial=False) == "tls_mode must be one of 'none', 'starttls', 'ssl'"
    assert _validate_smtp_payload({"use_tls": True}, partial=False) == "use_tls / use_ssl are no longer accepted. Use tls_mode ('none' | 'starttls' | 'ssl') instead."
    assert _validate_smtp_payload({"use_ssl": True}, partial=False) == "use_tls / use_ssl are no longer accepted. Use tls_mode ('none' | 'starttls' | 'ssl') instead."

    # Auth validation (username)
    assert _validate_smtp_payload({"use_auth": True, "username": ""}, partial=False) == "use_auth=True requires a non-empty username"
    assert _validate_smtp_payload({"use_auth": True}, partial=False) == "use_auth=True requires a non-empty username"
    assert _validate_smtp_payload({"use_auth": True}, partial=True) is None  # allowed on partial if not changing username

    # Port validation
    assert _validate_smtp_payload({"port": "not-a-number"}, partial=False) == "port must be a number"
    assert _validate_smtp_payload({"port": 0}, partial=False) == "port must be between 1 and 65535"
    assert _validate_smtp_payload({"port": 65536}, partial=False) == "port must be between 1 and 65535"
    assert _validate_smtp_payload({"port": 587}, partial=False) is None

    # Password validation
    assert _validate_smtp_payload({"password": "x" * 257}, partial=False) == "password is too long (max 256 chars)"

    # Valid check
    assert _validate_smtp_payload({"host": "smtp.ex.com", "tls_mode": "starttls", "port": 587}, partial=False) is None


def test_api_list_smtp(client, auth_headers, db_session):
    # Add SMTP Server
    s = SMTPServer(name="ListSMTP", host="smtp.ex.com", port=587, use_auth=False, is_enabled=True)
    # Add a second server with no logs to cover lines 146-147
    s_no_logs = SMTPServer(name="NoLogsSMTP", host="smtp2.ex.com", port=587, use_auth=False, is_enabled=True)
    db_session.add_all([s, s_no_logs])
    db_session.commit()

    # Add some EmailLogs to aggregate statistics
    from datetime import datetime, UTC
    log_sent = EmailLog(
        recipient_email="ok@ex.com",
        smtp_server_name="ListSMTP",
        status=EmailStatus.SENT,
        sent_at=datetime.now(UTC)
    )
    log_fail = EmailLog(
        recipient_email="fail@ex.com",
        smtp_server_name="ListSMTP",
        status=EmailStatus.FAILED,
        failed_at=datetime.now(UTC)
    )
    db_session.add_all([log_sent, log_fail])
    db_session.commit()

    # Mock connection pool status
    mock_pool = MagicMock()
    mock_pool.get_status.return_value = {
        "ListSMTP": {
            "minute_count": 10,
            "avg_handshake_latency": 0.15,
            "avg_send_latency": 0.25
        }
    }

    with patch("mercury.engine.connection_pool.iter_active_pools", return_value=[mock_pool]):
        response = client.get("/api/smtp", headers=auth_headers)
        assert response.status_code == 200
        res = response.get_json()
        assert len(res["servers"]) > 0
        server_dict = [x for x in res["servers"] if x["name"] == "ListSMTP"][0]
        assert server_dict["current_minute_count"] == 10
        assert server_dict["avg_handshake_latency"] == 0.15
        assert server_dict["avg_send_latency"] == 0.25
        # Total sent/failed updated from logs
        assert server_dict["total_sent"] == 1
        assert server_dict["total_failed"] == 1

        no_logs_dict = [x for x in res["servers"] if x["name"] == "NoLogsSMTP"][0]
        assert no_logs_dict["total_sent"] == 0
        assert no_logs_dict["total_failed"] == 0


def test_api_list_smtp_connection_pool_exception(client, auth_headers, db_session):
    s = SMTPServer(name="ListSMTP2", host="smtp.ex.com", port=587, use_auth=False, is_enabled=True)
    db_session.add(s)
    db_session.commit()

    # Cause connection pool iteration to raise an exception to cover lines 104-105
    with patch("mercury.engine.connection_pool.iter_active_pools", side_effect=Exception("Pool iteration error")):
        response = client.get("/api/smtp", headers=auth_headers)
        assert response.status_code == 200
        res = response.get_json()
        assert len(res["servers"]) > 0


def test_api_list_smtp_query_exception(client, auth_headers, db_session):
    s = SMTPServer(name="ListSMTP3", host="smtp.ex.com", port=587, use_auth=False, is_enabled=True)
    db_session.add(s)
    db_session.commit()

    # Cause query execution to fail to cover lines 134-137
    with patch("sqlalchemy.orm.query.Query.all", side_effect=Exception("DB Query failure")):
        response = client.get("/api/smtp", headers=auth_headers)
        assert response.status_code == 200
        res = response.get_json()
        assert len(res["servers"]) > 0


def test_api_list_smtp_db_commit_error(client, auth_headers, db_session):
    s = SMTPServer(name="CommitErrSMTP", host="smtp.ex.com", port=587, total_sent=0, is_enabled=True)
    db_session.add(s)
    db_session.commit()

    # Add logs so stats update
    from datetime import datetime, UTC
    log = EmailLog(
        recipient_email="ok@ex.com",
        smtp_server_name="CommitErrSMTP",
        status=EmailStatus.SENT,
        sent_at=datetime.now(UTC)
    )
    db_session.add(log)
    db_session.commit()

    # Cause commit failure in list route to cover lines 154-162
    with patch("sqlalchemy.orm.Session.commit", side_effect=Exception("Database crash")):
        response = client.get("/api/smtp", headers=auth_headers)
        # Should still succeed and return the list because of try-except block
        assert response.status_code == 200


def test_api_add_smtp_validation(client, auth_headers):
    # Host required
    response = client.post("/api/smtp", headers=auth_headers, json={"name": "NoHost"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "Host required"

    # Validation failure
    response = client.post("/api/smtp", headers=auth_headers, json={"host": "smtp.ex.com", "tls_mode": "invalid"})
    assert response.status_code == 400


def test_api_add_smtp_success(client, auth_headers, db_session):
    payload = {
        "name": "NewServer",
        "host": "smtp.new.com",
        "port": 465,
        "username": "user",
        "password": "pwd",
        "tls_mode": "ssl",
        "from_email": "from@new.com",
        "from_name": "New Sender"
    }
    response = client.post("/api/smtp", headers=auth_headers, json=payload)
    assert response.status_code == 200
    res = response.get_json()
    assert res["success"] is True
    assert res["server"]["name"] == "NewServer"

    # Verify DB record
    db_session.expire_all()
    s = db_session.query(SMTPServer).filter_by(name="NewServer").first()
    assert s is not None
    assert s.host == "smtp.new.com"
    assert s.port == 465
    assert s.from_email == "from@new.com"
    assert s.from_name == "New Sender"


def test_api_add_smtp_runtime_failure(client, auth_headers):
    # Simulate a RuntimeError (e.g., encryption exception)
    with patch("mercury.services.smtp_service.SMTPService.add_server", side_effect=RuntimeError("Encrypt fail")):
        response = client.post("/api/smtp", headers=auth_headers, json={"host": "smtp.ex.com"})
        assert response.status_code == 500
        assert response.get_json()["error"] == "Encrypt fail"


def test_api_test_smtp_endpoints(client, auth_headers, db_session):
    # Not found
    response = client.post("/api/smtp/test/UnknownSMTP", headers=auth_headers)
    assert response.status_code == 404
    assert response.get_json()["error"] == "Server not found"

    # Success
    s = SMTPServer(name="TestSMTPRun", host="smtp.ex.com", port=587, is_enabled=True)
    db_session.add(s)
    db_session.commit()

    with patch("mercury.web.routes.api.smtp.run_async", return_value={"success": True}):
        response = client.post(f"/api/smtp/test/{s.name}", headers=auth_headers)
        assert response.status_code == 200
        assert response.get_json()["success"] is True


def test_api_update_smtp_errors(client, auth_headers, db_session):
    # 1. Validation error
    response = client.put("/api/smtp/SomeServer", headers=auth_headers, json={"port": "invalid"})
    assert response.status_code == 400

    # 2. Server not found
    response = client.put("/api/smtp/UnknownServer", headers=auth_headers, json={"host": "smtp.new.com"})
    assert response.status_code == 404

    # 3. Post-merge username check failure
    s = SMTPServer(name="NoUserSMTP", host="smtp.ex.com", port=587, username="", use_auth=False)
    db_session.add(s)
    db_session.commit()

    response = client.put(f"/api/smtp/{s.name}", headers=auth_headers, json={"use_auth": True})
    assert response.status_code == 400
    assert "use_auth=True requires a non-empty username" in response.get_json()["error"]


def test_api_update_smtp_success(client, auth_headers, db_session):
    s = SMTPServer(name="UpdateSMTP", host="smtp.ex.com", port=587, username="old", password="old", use_auth=True)
    db_session.add(s)
    db_session.commit()

    payload = {
        "name": "UpdatedSMTP",
        "host": "smtp.updated.com",
        "port": 465,
        "username": "new_user",
        "password": "new_password",
        "from_email": "updated@ex.com",
        "from_name": "Updated Sender",
        "tls_mode": "ssl",
        "use_auth": True
    }

    mock_pool = MagicMock()
    with patch("mercury.engine.connection_pool.iter_active_pools", return_value=[mock_pool]), \
         patch("mercury.web.routes.api.smtp.run_async") as mock_run:
        response = client.put(f"/api/smtp/{s.name}", headers=auth_headers, json=payload)
        assert response.status_code == 200
        assert response.get_json()["success"] is True
        mock_run.assert_called_once()

    db_session.expire_all()
    fresh = db_session.query(SMTPServer).filter_by(name="UpdatedSMTP").first()
    assert fresh is not None
    assert fresh.host == "smtp.updated.com"
    assert fresh.port == 465
    assert fresh.username == "new_user"
    assert fresh.from_email == "updated@ex.com"
    assert fresh.from_name == "Updated Sender"


def test_api_update_smtp_pool_exception(client, auth_headers, db_session):
    s = SMTPServer(name="PoolErrSMTP", host="smtp.ex.com", port=587)
    db_session.add(s)
    db_session.commit()

    mock_pool = MagicMock()
    mock_pool.invalidate_server.side_effect = Exception("Invalidation error")

    # Invalidation exception should be swallowed silently (cover lines 310-314)
    with patch("mercury.engine.connection_pool.iter_active_pools", return_value=[mock_pool]):
        response = client.put(f"/api/smtp/{s.name}", headers=auth_headers, json={"host": "smtp.new.com"})
        assert response.status_code == 200
        assert response.get_json()["success"] is True


def test_api_update_smtp_name_conflict(client, auth_headers, db_session):
    s1 = SMTPServer(name="SMTP1", host="smtp.ex.com", port=587)
    s2 = SMTPServer(name="SMTP2", host="smtp2.ex.com", port=587)
    db_session.add_all([s1, s2])
    db_session.commit()

    # Try renaming SMTP1 to SMTP2
    response = client.put(f"/api/smtp/{s1.name}", headers=auth_headers, json={"name": "SMTP2"})
    assert response.status_code == 400
    assert "Server name 'SMTP2' is already in use" in response.get_json()["error"]


def test_api_update_smtp_password_encryption_error(client, auth_headers, db_session):
    s = SMTPServer(name="EncErrSMTP", host="smtp.ex.com", port=587)
    db_session.add(s)
    db_session.commit()

    # Mock get_encryption_service to throw an exception on encrypt
    with patch("mercury.security.encryption.get_encryption_service") as mock_get:
        mock_service = MagicMock()
        mock_service.encrypt.side_effect = Exception("Encryption failure")
        mock_get.return_value = mock_service

        response = client.put(f"/api/smtp/{s.name}", headers=auth_headers, json={"password": "new_password"})
        # Should raise 500
        assert response.status_code == 500
        assert "encryption failed" in response.get_json()["error"]


def test_api_delete_smtp(client, auth_headers, db_session):
    s = SMTPServer(name="DelSMTP", host="smtp.ex.com", port=587)
    db_session.add(s)
    db_session.commit()

    # Not found
    response = client.delete("/api/smtp/UnknownSMTP", headers=auth_headers)
    assert response.status_code == 404

    # Success
    response = client.delete(f"/api/smtp/{s.name}", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    db_session.expire_all()
    assert db_session.query(SMTPServer).filter_by(name="DelSMTP").first() is None


def test_api_smtp_health_status(client, auth_headers, db_session):
    s = SMTPServer(name="HealthSMTP", host="smtp.ex.com", port=587, settings={
        "last_checked_at": "2026-01-01T00:00:00",
        "health_error": "Timeout",
        "health_error_type": "ConnectionTimeout"
    })
    db_session.add(s)
    db_session.commit()

    response = client.get("/api/smtp/health", headers=auth_headers)
    assert response.status_code == 200
    res = response.get_json()
    server_dict = [x for x in res["servers"] if x["name"] == "HealthSMTP"][0]
    assert server_dict["last_checked_at"] == "2026-01-01T00:00:00"
    assert server_dict["health_error"] == "Timeout"
    assert server_dict["health_error_type"] == "ConnectionTimeout"


def test_api_trigger_smtp_health_checks(client, auth_headers, db_session):
    # No enabled SMTP servers
    response = client.post("/api/smtp/health/check", headers=auth_headers)
    assert response.status_code == 400
    assert response.get_json()["error"] == "No enabled SMTP servers configured"

    # Enabled SMTP server exists
    s = SMTPServer(name="EnabledSMTP", host="smtp.ex.com", port=587, is_enabled=True)
    db_session.add(s)
    db_session.commit()

    with patch("mercury.services.smtp_service.SMTPService.check_all_health") as mock_health, \
         patch("mercury.web.routes.api.smtp.run_async", return_value={"EnabledSMTP": "ok"}) as mock_run:
        response = client.post("/api/smtp/health/check", headers=auth_headers)
        assert response.status_code == 200
        res = response.get_json()
        assert res["success"] is True
        assert res["results"] == {"EnabledSMTP": "ok"}
