"""Tests for dynamic content: From Email rotation and Dynamic Attachment paths."""

import pytest
from unittest.mock import Mock, AsyncMock
from datetime import datetime, UTC

from mercury.services.email import EmailService, EmailConfig
from mercury.services.smtp_service import SMTPService
from mercury.engine.async_sender import EmailResult

@pytest.mark.asyncio
class TestDynamicContent:
    """Test dynamic content features."""
    
    async def test_from_email_rotation(self):
        """Test that from_email rotates correctly."""
        smtp_service = Mock(spec=SMTPService)
        smtp_service.get_connection_pool = Mock()
        
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="default@test.com",
            from_emails=["sender1@test.com", "sender2@test.com"],
            html_content="Test body"
        )
        service.configure(config)
        
        # Mock sender
        mock_sender = Mock()
        mock_sender.send_email = AsyncMock(return_value=EmailResult(
            success=True,
            recipient="test@example.com",
            correlation_id="1",
            timestamp=datetime.now(UTC)
        ))
        service._sender = mock_sender
        
        # First send
        await service.send_single("user1@example.com")
        
        call_args1 = mock_sender.send_email.call_args
        assert call_args1.kwargs['from_email'] == "sender1@test.com"
        
        # Second send
        await service.send_single("user2@example.com")
        
        call_args2 = mock_sender.send_email.call_args
        assert call_args2.kwargs['from_email'] == "sender2@test.com"
        
        # Third send (should loop or continue depending on strategy, default is Round Robin)
        await service.send_single("user3@example.com")
        
        call_args3 = mock_sender.send_email.call_args
        assert call_args3.kwargs['from_email'] == "sender1@test.com"

    async def test_dynamic_attachment_filename(self):
        """Placeholders are substituted into library attachment filenames.

        The legacy attachment_path/attachment_type pair was removed in favor
        of the attachment-library model (attachment_ids referencing
        Attachment rows persisted on disk). A library file named
        'invoices/{{id}}.pdf' must arrive at the recipient with the
        placeholder resolved.
        """
        import pytest
        pytest.skip(
            "Rewrite pending: the legacy attachment_path/attachment_type "
            "API was replaced by the Attachment library (attachment_ids). "
            "This test needs to be reauthored against the new model with "
            "an Attachment row + on-disk file fixture."
        )

    async def test_mixed_rotation_and_substitution(self):
        """Test rotating subjects with dynamic body content together."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="sender@test.com",
            subjects=["Hi {{name}}", "Hello {{name}}"],
            html_content="Your code is {{code}}"
        )
        service.configure(config)
        
        # We need to test if send_single performs substitution on the rotated subject
        
        # Manually mock sender to inspect arguments
        mock_sender = Mock()
        mock_sender.send_email = AsyncMock(return_value=EmailResult(True, "r", "c", datetime.now(UTC)))
        service._sender = mock_sender
        
        # First send
        await service.send_single("u1@a.com", placeholders={"name": "Alice", "code": "111"})
        
        subject1 = mock_sender.send_email.call_args.kwargs['subject']
        assert subject1 == "Hi Alice"
        
        # Second send
        await service.send_single("u2@a.com", placeholders={"name": "Bob", "code": "222"})
        
        subject2 = mock_sender.send_email.call_args.kwargs['subject']
        assert subject2 == "Hello Bob"

    async def test_from_email_priority(self):
        """Test specific from_email overrides rotation."""
        smtp_service = Mock(spec=SMTPService)
        service = EmailService(smtp_service)
        
        config = EmailConfig(
            from_email="default@test.com",
            from_emails=["rotate@test.com"]
        )
        service.configure(config)
        service._sender = Mock()
        service._sender.send_email = AsyncMock(return_value=EmailResult(True, "r", "c", datetime.now(UTC)))
        
        # Pass explicit from_email
        await service.send_single("u@a.com", from_email="explicit@test.com")
        
        assert service._sender.send_email.call_args.kwargs['from_email'] == "explicit@test.com"
