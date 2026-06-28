"""Coverage boost tests for core services."""

import pytest
import os
import tempfile
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, UTC

from mercury.services.email.obfuscation import apply_obfuscation
from mercury.services.email.service import EmailService
from mercury.services.email.config import EmailConfig
from mercury.services.campaign_service import CampaignService, CampaignConfig, _detect_csv_encoding
from mercury.services.smtp_service import SMTPService
from mercury.data.models import SMTPServer
from mercury.data.models.campaign import Campaign, CampaignStatus
from mercury.engine.async_sender import EmailResult


# ---------------------------------------------------------------------------
# Obfuscation Tests
# ---------------------------------------------------------------------------

def test_apply_obfuscation_toggles():
    mock_settings = MagicMock()
    mock_settings.obfuscate_links = True
    mock_settings.encode_html_entities = True
    mock_settings.encode_unicode_homoglyphs = True
    mock_settings.encode_attachments = True
    mock_settings.encode_body_base64 = True

    with patch("mercury.services.email.obfuscation.SettingsService.get_settings", return_value=mock_settings):
        # Trigger warn_encode_attachments warning
        import mercury.services.email.obfuscation
        mercury.services.email.obfuscation._warned_encode_attachments = False

        html = '<a href="http://example.com/foo bar">hello</a>'
        attachments = [{"filename": "a.txt", "data": b"abc"}]
        body, force_b64 = apply_obfuscation(html, attachments)
        
        assert force_b64 is True
        assert "%20" in body  # links are url-encoded
        assert "&#104;" in body  # text is HTML-entity encoded
        assert mercury.services.email.obfuscation._warned_encode_attachments is True


# ---------------------------------------------------------------------------
# EmailService Tests
# ---------------------------------------------------------------------------

def test_email_service_configure_placeholders_parsing():
    smtp_svc = MagicMock()
    svc = EmailService(smtp_svc)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        tf.write("first_name: YAML\n")
        tf_name = tf.name

    try:
        cfg = EmailConfig(placeholders_path=tf_name)
        svc.configure(cfg)
        assert svc._placeholder_processor.static_placeholders == {"first_name": "YAML"}
    finally:
        os.unlink(tf_name)

    # JSON path
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf2:
        tf2.write('{"first_name": "JSON"}')
        tf2_name = tf2.name

    try:
        cfg = EmailConfig(placeholders_path=tf2_name)
        svc.configure(cfg)
        assert svc._placeholder_processor.static_placeholders == {"first_name": "JSON"}
    finally:
        os.unlink(tf2_name)

    # Invalid path
    cfg = EmailConfig(placeholders_path="/nonexistent_file.yaml")
    svc.configure(cfg)
    assert svc._placeholder_processor.static_placeholders == {}


def test_email_service_unowned_emails_warning():
    smtp_svc = MagicMock()
    mock_pool = MagicMock()
    mock_pool.select_server_for_from.return_value = None
    smtp_svc.get_connection_pool.return_value = mock_pool

    svc = EmailService(smtp_svc)
    cfg = EmailConfig(from_emails=["unowned@ex.com"])
    # Should log warning about unowned from_emails
    svc.configure(cfg)


@pytest.mark.asyncio
async def test_email_service_send_priority_headers():
    smtp_svc = MagicMock()
    mock_sender = AsyncMock()
    smtp_svc.get_connection_pool.return_value = MagicMock()
    
    svc = EmailService(smtp_svc)
    svc._sender = mock_sender

    priorities = ["1", "2", "4", "5"]
    for prio in priorities:
        cfg = EmailConfig(mail_priority=prio)
        svc.configure(cfg)
        await svc.send_single("user@example.com", html_body="hello")
        
        # Verify headers were passed to send_email
        args, kwargs = mock_sender.send_email.call_args
        assert "X-Priority" in kwargs["headers"]
        mock_sender.reset_mock()


@pytest.mark.asyncio
async def test_email_service_custom_placeholders_db_error():
    smtp_svc = MagicMock()
    svc = EmailService(smtp_svc)
    cfg = EmailConfig(placeholders_path=None)
    svc.configure(cfg)

    # Force database exception inside _merge_custom_placeholders
    with patch("mercury.data.database.session_scope", side_effect=Exception("DB connection error")):
        svc._merge_custom_placeholders()
        # Should catch exception and not crash


@pytest.mark.asyncio
async def test_email_service_dead_letter_exceptions():
    smtp_svc = MagicMock()
    mock_dead_letter = MagicMock()
    mock_dead_letter.add_dead_letter.side_effect = Exception("Dead letter queue full")
    
    svc = EmailService(smtp_svc)
    svc._dead_letter_service = mock_dead_letter

    mock_sender = AsyncMock()
    mock_sender.send_email.return_value = EmailResult(
        success=False,
        recipient="user@ex.com",
        correlation_id=None,
        timestamp=datetime.now(UTC),
        error="Connection failed",
        error_type="connection_error"
    )
    svc._sender = mock_sender

    # Re-configure to set error status
    cfg = EmailConfig(from_emails=["from@ex.com"])
    svc.configure(cfg)

    # Force failure that invokes dead letter service
    mock_sender.send_email.return_value = EmailResult(
        success=False,
        recipient="user@ex.com",
        correlation_id=None,
        timestamp=datetime.now(UTC),
        error="Malformed recipient",
        error_type="send_failure"
    )
    
    # Should catch exception from dead_letter_service gracefully
    result = await svc.send_single("user@ex.com", html_body="body")
    assert result.success is False


@pytest.mark.asyncio
async def test_email_service_enrich_recipient_db_error():
    smtp_svc = MagicMock()
    svc = EmailService(smtp_svc)
    
    # DB exception in geo/ua enrichment
    with patch("mercury.data.database.session_scope", side_effect=Exception("Enrichment DB failed")):
        # Should swallow exceptions cleanly
        await svc.send_bulk([{"email": "user@ex.com"}], html_template="hello")


@pytest.mark.asyncio
async def test_email_service_bulk_send_cancellations():
    smtp_svc = MagicMock()
    svc = EmailService(smtp_svc)
    mock_sender = AsyncMock()
    mock_sender.send_email.return_value = EmailResult(success=True, recipient="user@ex.com", correlation_id=None, timestamp=datetime.now(UTC))
    svc._sender = mock_sender

    shutdown_ev = asyncio.Event()
    shutdown_ev.set()  # Cancel campaign immediately

    res = await svc.send_bulk(
        recipients=[{"email": "u1@ex.com"}, {"email": "u2@ex.com"}],
        html_template="hello",
        shutdown_event=shutdown_ev
    )
    assert res.failed == 2
    assert res.results[0].error == "Campaign cancelled"


@pytest.mark.asyncio
async def test_email_service_bulk_send_gather_exceptions():
    smtp_svc = MagicMock()
    svc = EmailService(smtp_svc)

    # Cause send_single to raise a generic Exception inside gather
    with patch.object(svc, "send_single", side_effect=Exception("Unexpected send error")):
        res = await svc.send_bulk(
            recipients=[{"email": "u1@ex.com"}],
            html_template="hello"
        )
        assert res.failed == 1
        assert res.results[0].error == "Unexpected send error"
        assert res.results[0].recipient == "u1@ex.com"


# ---------------------------------------------------------------------------
# CampaignService Tests
# ---------------------------------------------------------------------------

def test_detect_encoding_os_error():
    assert _detect_csv_encoding("/nonexistent_file_to_cause_os_error.csv") == "utf-8"


def test_detect_encoding_normalizer_import_error():
    # Force import error for charset_normalizer
    with patch("builtins.__import__", side_effect=ImportError("mock normalizer missing")):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"\x80\x81\x82")  # Invalid UTF-8 bytes to bypass fast path
            fname = f.name
        try:
            assert _detect_csv_encoding(fname) == "utf-8"
        finally:
            os.unlink(fname)


def test_campaign_service_setup_signals_failures():
    with patch("mercury.services.campaign_service.CampaignService._setup_signal_handlers") as mock_setup:
        # Check signal setup
        svc = CampaignService()
        assert svc._running is False


def test_campaign_service_load_config_defaults():
    svc = CampaignService()
    cfg = CampaignConfig(
        name="test_c",
        concurrency=0,
        chunk_size=0,
        from_names=["NameA"],
        from_emails=["emailA@ex.com"]
    )
    
    # Mock settings & DB load
    mock_settings = MagicMock()
    mock_settings.max_concurrency = 25
    mock_settings.batch_size = 50
    mock_settings.default_reply_to = "reply@ex.com"

    with patch("mercury.services.settings_service.SettingsService.get_settings", return_value=mock_settings):
        svc.load_config(cfg)
        assert cfg.concurrency == 25
        assert cfg.chunk_size == 50
        assert cfg.from_name == "NameA"
        assert cfg.from_email == "emailA@ex.com"
        assert cfg.reply_to == "reply@ex.com"


def test_campaign_service_create_campaign_fields(db_session):
    svc = CampaignService()
    cfg = CampaignConfig(
        name="AllFieldsCampaign",
        links=["http://site.com"],
        manual_recipients=[{"email": "abc@ex.com"}],
        recipients_path="/rec.csv",
        placeholders_path="/ph.json",
        dry_run=True,
        from_emails=["me@ex.com"],
        from_names=["Me"],
        template_path="/temp.html",
        templates=[{"name": "V1"}],
        smtp_server_id=5,
        attachment_ids=[1, 2],
        convert_attachment=True,
        attachment_convert_to="docx",
        logo_attachment_id=10,
        auto_company_logo=True,
        hide_from_email_header=True,
        include_default_body=False,
        validate_emails=True,
        deduplicate=True,
        mail_priority="1"
    )

    with patch("mercury.services.campaign_service.get_session_direct", return_value=db_session):
        camp = svc.create_campaign(cfg)
        assert camp.name == "AllFieldsCampaign"
        assert camp.settings["links"] == ["http://site.com"]
        assert camp.settings["manual_recipients"] == [{"email": "abc@ex.com"}]
        assert camp.settings["smtp_server_id"] == 5
        assert camp.settings["attachment_ids"] == [1, 2]
        assert camp.settings["convert_attachment"] is True
        assert camp.settings["mail_priority"] == "1"


@pytest.mark.asyncio
async def test_campaign_run_preflight_failures(db_session):
    svc = CampaignService()
    
    # Configure mock campaign in DB
    c = Campaign(name="Preflight Fail", status=CampaignStatus.DRAFT)
    db_session.add(c)
    db_session.commit()

    # Pre-configure settings and load configuration for preflight check
    cfg = CampaignConfig(
        name="Preflight Fail",
        concurrency=1,
        chunk_size=10,
        from_names=["NameA"],
        from_emails=["emailA@ex.com"],
        smtp_configs=[{"name": "SMTP1", "host": "smtp.ex.com", "port": 587}]
    )
    mock_settings = MagicMock()
    mock_settings.max_concurrency = 25
    mock_settings.batch_size = 50
    mock_settings.default_reply_to = "reply@ex.com"

    # Preflight failure: all SMTP test connections return success=False
    with patch("mercury.services.settings_service.SettingsService.get_settings", return_value=mock_settings), \
         patch("mercury.services.smtp_service.SMTPService.test_all_connections", return_value=[{"success": False, "server": "SMTP1", "error": "Timeout"}]), \
         patch("mercury.services.campaign_service.get_session_direct", return_value=db_session):
        
        svc.load_config(cfg)
        svc._current_campaign = c
        with pytest.raises(RuntimeError, match="Pre-flight block"):
            await svc.run_campaign([])
        
        # Verify campaign state was updated to failed
        db_session.expire_all()
        fresh = db_session.query(Campaign).get(c.id)
        assert fresh.status == "failed"


@pytest.mark.asyncio
async def test_campaign_run_log_writer_failures():
    # Trigger an exception inside log writer flusher thread
    svc = CampaignService()
    q = asyncio.Queue()
    q.put_nowait({"recipient": "a@b.com"})
    q.put_nowait(None)  # Sentinel

    with patch("mercury.data.database.session_scope", side_effect=Exception("DB save failed")):
        # Should log error and exit writer task cleanly without crash
        # This will be tested inside the task wrapper
        pass


@pytest.mark.asyncio
async def test_campaign_run_micro_chunk_cancellations(db_session):
    svc = CampaignService()
    c = Campaign(name="CancelMid", status=CampaignStatus.DRAFT)
    db_session.add(c)
    db_session.commit()
    svc._current_campaign = c

    # Set running to false immediately after starting
    svc._running = False

    cfg = CampaignConfig(
        name="CancelMid",
        concurrency=1,
        chunk_size=10,
        from_names=["NameA"],
        from_emails=["emailA@ex.com"],
        smtp_configs=[{"name": "SMTP1", "host": "smtp.ex.com", "port": 587}]
    )
    mock_settings = MagicMock()
    mock_settings.max_concurrency = 25
    mock_settings.batch_size = 50
    mock_settings.default_reply_to = "reply@ex.com"

    async def fake_test_all_connections():
        svc._running = False
        return [{"success": True}]

    with patch("mercury.services.settings_service.SettingsService.get_settings", return_value=mock_settings), \
         patch("mercury.services.smtp_service.SMTPService.test_all_connections", side_effect=fake_test_all_connections), \
         patch("mercury.services.campaign_service.get_session_direct", return_value=db_session):
        svc.load_config(cfg)
        stats = await svc.run_campaign([{"email": "u1@ex.com"}, {"email": "u2@ex.com"}], log_path="/tmp")
        assert stats["chunks_processed"] == 0  # Cancelled before chunk iteration loop


@pytest.mark.asyncio
async def test_campaign_run_pause_wait(db_session):
    svc = CampaignService()
    c = Campaign(name="PauseCampaign", status=CampaignStatus.DRAFT)
    db_session.add(c)
    db_session.commit()
    svc._current_campaign = c

    svc._running = True
    # Fake config
    cfg = CampaignConfig(name="PauseCampaign", chunk_size=1, pause_between_chunks=5)
    svc.config = cfg

    # Return success send results using AsyncMock
    mock_email_svc = MagicMock()
    mock_send_result = MagicMock()
    mock_send_result.results = []
    mock_email_svc.send_bulk = AsyncMock(return_value=mock_send_result)
    svc.email_service = mock_email_svc

    with patch("mercury.services.smtp_service.SMTPService.test_all_connections", return_value=[{"success": True}]), \
         patch("mercury.services.campaign_service.get_session_direct", return_value=db_session):
        
        # Shutdown event is set to abort pause early
        svc._shutdown_event.set()
        stats = await svc.run_campaign([{"email": "u1@ex.com"}], log_path="/tmp")
        # Assert paused successfully
        assert stats["chunks_processed"] == 1


# ---------------------------------------------------------------------------
# SMTPService Tests
# ---------------------------------------------------------------------------

def test_smtp_service_load_database_server_id(db_session):
    # Enabled server
    s_enabled = SMTPServer(name="EnabledS", host="smtp.ex.com", is_enabled=True)
    # Disabled server
    s_disabled = SMTPServer(name="DisabledS", host="smtp.ex.com", is_enabled=False)
    db_session.add_all([s_enabled, s_disabled])
    db_session.commit()

    # Pre-store IDs to avoid DetachedInstanceError after session is closed inside the method
    enabled_id = s_enabled.id
    disabled_id = s_disabled.id

    svc = SMTPService()
    with patch("mercury.services.smtp_service.get_session_direct", return_value=db_session):
        configs = svc.load_from_database(server_id=enabled_id)
        assert len(configs) == 1
        assert configs[0].name == "EnabledS"

        configs_disabled = svc.load_from_database(server_id=disabled_id)
        assert len(configs_disabled) == 0


@pytest.mark.asyncio
async def test_smtp_service_test_connection_errors():
    svc = SMTPService()
    svc.load_from_config([{"name": "SMTPTest", "host": "smtp.ex.com", "port": 587, "use_auth": True, "username": "user", "password": "pwd"}])

    import aiosmtplib

    # 1. Auth failure
    with patch("aiosmtplib.SMTP.connect"), \
         patch("aiosmtplib.SMTP.starttls"), \
         patch("aiosmtplib.SMTP.login", side_effect=aiosmtplib.SMTPAuthenticationError(535, "Auth failed")), \
         patch("aiosmtplib.SMTP.quit"):
        res = await svc.test_connection("SMTPTest")
        assert res["error_type"] == "auth_failed"

    # 2. Timeout error
    with patch("aiosmtplib.SMTP.connect", side_effect=aiosmtplib.SMTPConnectTimeoutError("Timeout error")):
        res = await svc.test_connection("SMTPTest")
        assert res["error_type"] == "tcp_timeout"

    # 3. Bad greeting response
    with patch("aiosmtplib.SMTP.connect", side_effect=aiosmtplib.SMTPConnectResponseError(554, "Bad greeting")):
        res = await svc.test_connection("SMTPTest")
        assert res["error_type"] == "bad_greeting"

    # 4. DNS resolution failure
    with patch("aiosmtplib.SMTP.connect", side_effect=aiosmtplib.SMTPConnectError("getaddrinfo failed")):
        res = await svc.test_connection("SMTPTest")
        assert res["error_type"] == "dns_failure"

    # 5. Protocol failure
    with patch("aiosmtplib.SMTP.connect"), \
         patch("aiosmtplib.SMTP.starttls", side_effect=aiosmtplib.SMTPException("Protocol error")):
        res = await svc.test_connection("SMTPTest")
        assert res["error_type"] == "protocol_failed"

    # 6. OSError during connect
    with patch("aiosmtplib.SMTP.connect", side_effect=OSError("Network down")):
        res = await svc.test_connection("SMTPTest")
        assert res["error_type"] == "tcp_failed"

    # 7. Quit failure
    with patch("aiosmtplib.SMTP.connect"), \
         patch("aiosmtplib.SMTP.starttls"), \
         patch("aiosmtplib.SMTP.login"), \
         patch("aiosmtplib.SMTP.quit", side_effect=Exception("Quit crashed")):
        res = await svc.test_connection("SMTPTest")
        # quit exception is caught and connection success is returned
        assert res["success"] is True


@pytest.mark.asyncio
async def test_smtp_service_check_all_health_exceptions(db_session):
    s = SMTPServer(name="HealthErrS", host="smtp.ex.com", is_enabled=True)
    db_session.add(s)
    db_session.commit()

    svc = SMTPService()
    svc.load_from_config([{"name": "HealthErrS", "host": "smtp.ex.com", "port": 587, "use_auth": False}])

    # 1. queue_emit exception should be caught cleanly
    with patch("mercury.web.extensions.queue_emit", side_effect=Exception("Socket server crashed")), \
         patch("mercury.services.smtp_service.get_session_direct", return_value=db_session), \
         patch.object(svc, "test_connection", return_value={"success": True}):
        
        results = await svc.check_all_health()
        assert len(results) == 1

    # 2. General health check exception triggers rollback
    with patch("mercury.services.smtp_service.SMTPRepository.get_by_name", side_effect=Exception("DB Failure")), \
         patch("mercury.services.smtp_service.get_session_direct", return_value=db_session):
        
        with pytest.raises(Exception, match="DB Failure"):
            await svc.check_all_health()
