"""Tests targeting full coverage of EmailService and config rotation options."""

import json
import asyncio
from unittest.mock import MagicMock, patch
import pytest
from mercury.services.email import EmailService
from mercury.services.email.config import EmailConfig
from mercury.engine.async_sender import EmailResult

@pytest.fixture
def smtp_service_mock():
    svc = MagicMock()
    # Mock connection pool
    mock_pool = MagicMock()
    svc.get_connection_pool.return_value = mock_pool
    return svc

def test_email_service_configure_json_placeholders(tmp_path, smtp_service_mock):
    # Setup json placeholders file
    p_file = tmp_path / "placeholders.json"
    p_data = {"global_var": "val1"}
    p_file.write_text(json.dumps(p_data))
    
    cfg = EmailConfig(
        placeholders_path=str(p_file),
        from_names=["Alice", "Bob"],
        from_emails=["a@b.com", "b@b.com"],
        templates=["t1.html", "t2.html"],
        subjects=["sub1", "sub2"],
        concurrency=10,
    )
    
    svc = EmailService(smtp_service_mock)
    svc.configure(cfg)
    
    assert svc._placeholder_processor.static_placeholders["global_var"] == "val1"
    assert svc._rotation_manager.is_registered("sender_identity")
    assert svc._rotation_manager.is_registered("templates")
    assert svc._rotation_manager.is_registered("subjects")

def test_email_service_configure_mismatched_lengths(smtp_service_mock, caplog):
    cfg = EmailConfig(
        from_names=["Alice"],
        from_emails=["a@b.com", "b@b.com"],
    )
    svc = EmailService(smtp_service_mock)
    svc.configure(cfg)
    # Paired rotation warning should be emitted due to mismatched lengths
    assert any("from_names" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_send_single_validation_errors(smtp_service_mock):
    svc = EmailService(smtp_service_mock)
    
    # 1. Malformed recipient
    result = await svc.send_single("invalidemail")
    assert result.success is False
    assert result.error_type == "invalid_recipient"
    
    # 2. Empty recipient
    result2 = await svc.send_single(None)
    assert result2.success is False

@pytest.mark.asyncio
async def test_send_single_qr_warnings(smtp_service_mock, caplog):
    svc = EmailService(smtp_service_mock)
    cfg = EmailConfig(
        html_content="<p>Scan here: {{qr_code}}</p>",
        enable_qr_code=False,  # disabled
    )
    svc.configure(cfg)
    
    # Mock get_sender/send_email to succeed
    from unittest.mock import AsyncMock
    mock_sender = MagicMock()
    mock_sender.send_email = AsyncMock(return_value=EmailResult(
        success=True, recipient="to@b.com", correlation_id="123", timestamp=MagicMock()
    ))
    svc._sender = mock_sender
    
    await svc.send_single("to@b.com", subject="Test")
    assert any("Template contains {{qr_code}} but" in record.message for record in caplog.records)

@pytest.mark.asyncio
async def test_send_single_bounce_processing(smtp_service_mock):
    svc = EmailService(smtp_service_mock)
    cfg = EmailConfig(from_emails=["a@b.com"])
    svc.configure(cfg)
    
    # Mock bounce service
    mock_bounce = MagicMock()
    from mercury.services.bounce_service import BounceType, BounceCategory
    mock_bounce.categorize_bounce.return_value = (BounceType.HARD, BounceCategory.INVALID_ADDRESS)
    svc.bounce_service = mock_bounce
    
    # Mock sender returning failure
    from unittest.mock import AsyncMock
    mock_sender = MagicMock()
    mock_sender.send_email = AsyncMock(return_value=EmailResult(
        success=False, recipient="to@b.com", correlation_id="123", timestamp=MagicMock(),
        error="550 User unknown", error_type="send_failure"
    ))
    svc._sender = mock_sender
    
    # Mock dead letter repository to avoid real DB access
    svc._dead_letter_service = MagicMock()
    
    result = await svc.send_single("to@b.com", subject="Test")
    assert result.success is False
    # Check bounce was categorized and processed
    mock_bounce.categorize_bounce.assert_called_once()
    mock_bounce.process_bounce.assert_called_once_with(
        email="to@b.com",
        error_message="550 User unknown",
        smtp_code=None,
        campaign_id=None
    )

def test_merge_custom_placeholders_exception(smtp_service_mock, caplog):
    svc = EmailService(smtp_service_mock)
    # mock processor
    svc._placeholder_processor = MagicMock(static_placeholders={})
    
    # Mock session scope to raise exception
    with patch("mercury.data.database.session_scope", side_effect=Exception("DB Down")):
        svc._merge_custom_placeholders()
        assert any("Could not load custom placeholders" in record.message for record in caplog.records)

def test_enrich_recipients_with_last_events(smtp_service_mock):
    svc = EmailService(smtp_service_mock)
    
    recipients = [
        {"email": "user1@b.com"}, # Needs enrichment
        {"email": "user2@b.com", "ip": "9.9.9.9", "ua": "Safari"}, # Already has UA/IP
    ]
    
    mock_session = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_last_events_bulk.return_value = {
        "user1@b.com": ("1.1.1.1", "Chrome")
    }
    
    with patch("mercury.data.database.session_scope") as mock_scope, \
         patch("mercury.data.repositories.logs.LogRepository", return_value=mock_repo):
        mock_scope.return_value.__enter__.return_value = mock_session
        svc._enrich_recipients_with_last_event(recipients)
        
    assert recipients[0]["ip"] == "1.1.1.1"
    assert recipients[0]["user_agent"] == "Chrome"
    # user2 should remain unchanged
    assert recipients[1]["ip"] == "9.9.9.9"

@pytest.mark.asyncio
async def test_send_bulk_cancelled(smtp_service_mock):
    svc = EmailService(smtp_service_mock)
    cfg = EmailConfig(concurrency=2)
    svc.configure(cfg)
    
    shutdown_event = asyncio.Event()
    shutdown_event.set() # pre-cancel
    
    recipients = [{"email": "to1@b.com"}]
    res = await svc.send_bulk(recipients, subject="Sub", html_template="Body", shutdown_event=shutdown_event)
    assert res.failed == 1
    assert res.results[0].error == "Campaign cancelled"

@pytest.mark.asyncio
async def test_send_bulk_wrapper_exception(smtp_service_mock):
    svc = EmailService(smtp_service_mock)
    cfg = EmailConfig(concurrency=2)
    svc.configure(cfg)
    
    # Mock send_single to raise Exception
    with patch.object(svc, "send_single", side_effect=Exception("Unexpected crash")):
        recipients = [{"email": "to1@b.com"}]
        res = await svc.send_bulk(recipients, subject="Sub", html_template="Body")
        assert res.failed == 1
        assert "Unexpected crash" in res.results[0].error
