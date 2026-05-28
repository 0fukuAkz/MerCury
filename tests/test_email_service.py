"""Tests for email service."""

import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime, UTC

from mercury.services.email import EmailService, EmailConfig
from mercury.services.smtp_service import SMTPService
from mercury.engine.async_sender import EmailResult


@pytest.mark.asyncio
class TestEmailService:
    """Test email service functionality."""
    
    async def test_configure(self):
        """Test service configuration."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="sender@test.com",
            from_name="Test Sender",
            subject="Test Subject",
            concurrency=25,
            dry_run=True
        )
        
        service.configure(config)
        
        assert service.config.from_email == "sender@test.com"
        assert service.config.concurrency == 25
        assert service.config.dry_run is True
    
    async def test_send_single_email(self):
        """Test sending single email."""
        smtp_service = Mock(spec=SMTPService)
        smtp_service.get_connection_pool = Mock()
        
        service = EmailService(smtp_service)
        service.configure(EmailConfig(
            from_email="sender@test.com",
            from_name="Sender",
            subject="Test",
            html_content="<p>Hello {{first_name}}!</p>"
        ))
        
        # Mock the sender
        mock_sender = Mock()
        mock_sender.send_email = AsyncMock(return_value=EmailResult(
            success=True,
            recipient="user@test.com",
            correlation_id="test-123",
            timestamp=datetime.now(UTC)
        ))
        
        service._sender = mock_sender
        
        result = await service.send_single(
            recipient="user@test.com",
            placeholders={"first_name": "John"}
        )

        assert result.success is True
        assert result.recipient == "user@test.com"

    async def test_send_single_invalid_recipient_no_at(self):
        """A recipient without '@' fails cleanly as invalid_recipient.

        Regression guard: a malformed address used to crash deep in a
        domain-parsing helper as 'list index out of range', which the bulk
        gather path then logged with recipient='unknown'. send_single now
        rejects it at the boundary before any helper parses it.
        """
        smtp_service = Mock(spec=SMTPService)
        smtp_service.get_connection_pool = Mock()

        service = EmailService(smtp_service)
        service.configure(EmailConfig(
            from_email="sender@test.com",
            subject="Test",
            html_content="<p>Hi</p>",
        ))
        # A sender that would explode if it were ever reached — proves the
        # guard short-circuits before any rendering/parsing.
        service._sender = Mock()
        service._sender.send_email = AsyncMock(side_effect=AssertionError("should not send"))

        result = await service.send_single(recipient="not-an-email")

        assert result.success is False
        assert result.error_type == "invalid_recipient"
        assert result.recipient == "not-an-email"

    async def test_send_single_with_rotation(self):
        """Test sending with subject rotation."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="sender@test.com",
            subjects=["Subject A", "Subject B", "Subject C"],
            html_content="<p>Test</p>"
        )
        
        service.configure(config)
        
        # Rotation manager should be configured
        assert service._rotation_manager is not None
        assert service._rotation_manager.is_registered('subjects')
    
    async def test_template_engine_integration(self):
        """Test template engine usage."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="sender@test.com",
            html_content="<p>Hello {{first_name}}, welcome to {{company}}!</p>"
        )
        
        service.configure(config)
        
        assert service._template_engine is not None
    
    async def test_tracking_service_integration(self):
        """Test tracking service integration."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="sender@test.com",
            enable_tracking=True,
            track_opens=True,
            track_clicks=True,
            tracking_base_url="https://track.example.com"
        )
        
        service.configure(config)
        
        assert service._tracking_service is not None
    
    async def test_get_statistics(self):
        """Test statistics retrieval."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(from_email="sender@test.com")
        service.configure(config)
        
        stats = service.get_statistics()
        
        assert 'config' in stats
        assert stats['config']['from_email'] == "sender@test.com"
        assert stats['config']['dry_run'] is False
    
    async def test_dry_run_mode(self):
        """Test dry run mode."""
        smtp_service = Mock(spec=SMTPService)
        smtp_service.get_connection_pool = Mock()
        
        service = EmailService(smtp_service)
        service.configure(EmailConfig(
            from_email="sender@test.com",
            subject="Test",
            html_content="<p>Test</p>",
            dry_run=True
        ))
        
        mock_sender = Mock()
        mock_sender.send_email = AsyncMock(return_value=EmailResult(
            success=True,
            recipient="user@test.com",
            correlation_id="test",
            timestamp=datetime.now(UTC),
            dry_run=True
        ))
        
        service._sender = mock_sender
        
        result = await service.send_single("user@test.com")
        
        assert result.success is True
        assert result.dry_run is True

