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

    async def test_dynamic_attachment_filename(self, db_engine, db_session, tmp_path, monkeypatch):
        """Placeholders are substituted into library attachment filenames.

        Replaces the previous legacy ``attachment_path`` / ``attachment_type``
        check. The current data model stores attachments as ``Attachment``
        rows + on-disk blobs under ``<data_dir>/attachments/<stored_name>``,
        and the email service references them via
        ``EmailConfig.attachment_ids``. A library file row named
        ``'invoices/{{first_name}}.pdf'`` must arrive at the recipient
        with the placeholder resolved, while the binary payload is left
        untouched (substitution would corrupt PDF bytes).
        """
        from sqlalchemy.orm import sessionmaker

        from mercury.data.models.attachment import Attachment
        from mercury.services.email.attachments import materialize_library_attachments
        from mercury.services.email.config import EmailConfig
        from mercury.services.email.context import SendContext
        from mercury.features.placeholders import PlaceholderProcessor

        # 1. Stage an on-disk attachment blob under a tmp data dir.
        attachments_dir = tmp_path / 'attachments'
        attachments_dir.mkdir()
        stored_name = 'fixture123.pdf'
        pdf_blob = b'%PDF-1.4\n%fixture binary payload'
        (attachments_dir / stored_name).write_bytes(pdf_blob)

        # 2. Point the materializer's get_data_dir() at our tmp_path so it
        #    reads the fixture blob (rather than the real user data dir).
        monkeypatch.setattr(
            'mercury.services.email.attachments.get_data_dir',
            lambda: tmp_path,
        )

        # 3. The materializer opens its own DB session via session_scope() →
        #    get_session_direct(). Route that at the test's in-memory engine
        #    so it can see the Attachment row we're about to commit.
        TestSession = sessionmaker(bind=db_engine)
        monkeypatch.setattr(
            'mercury.data.database.get_session_direct',
            TestSession,
        )

        # 4. Insert the Attachment row with a placeholder-templated filename.
        att = Attachment(
            filename='invoices/{{first_name}}.pdf',
            stored_name=stored_name,
            size_bytes=len(pdf_blob),
            content_type='application/pdf',  # binary → body NOT substituted
            is_active=True,
        )
        db_session.add(att)
        db_session.commit()

        # 5. Build the send-time context with attachment_ids + per-recipient
        #    placeholders.
        config = EmailConfig(
            from_email='sender@example.com',
            attachment_ids=[att.id],
        )
        ctx = SendContext(
            recipient='alice@example.com',
            placeholders={'first_name': 'Alice'},
            link=None,
            config=config,
        )

        # 6. Run the materializer and assert the rendered filename + intact
        #    payload + preserved content-type.
        materialized = materialize_library_attachments(
            ctx,
            body_extras={},
            header_extras={},
            placeholder_processor=PlaceholderProcessor(),
            attachment_generator=None,
        )

        assert len(materialized) == 1
        out = materialized[0]
        assert out['filename'] == 'invoices/Alice.pdf', (
            f"placeholder substitution failed: got {out['filename']!r}"
        )
        assert out['content_type'] == 'application/pdf'
        # Binary payload must be untouched — substitution on a PDF would
        # produce a corrupt attachment.
        assert out['data'] == pdf_blob

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
