"""Tests for async email sender."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock

from mercury.engine.async_sender import (
    AsyncEmailSender,
    BulkSendResult,
    categorize_smtp_error
)
from mercury.engine.connection_pool import SMTPServerConfig, SMTPConnectionPool
from mercury.engine.rate_limiter import RateLimiter, RateLimiterConfig
from mercury.exceptions import (
    SMTPConnectionError,
    SMTPAuthenticationError,
    SMTPRateLimitError,
    SMTPMailboxError,
    TransientSMTPError
)
import aiosmtplib


class TestErrorCategorization:
    """Test SMTP error categorization."""
    
    def test_connection_error(self):
        """Test connection error categorization."""
        error = ConnectionError("Connection refused")
        is_transient, error_type, exc = categorize_smtp_error(error)
        
        assert is_transient is True
        assert error_type == 'connection_error'
        assert isinstance(exc, SMTPConnectionError)
    
    def test_authentication_error(self):
        """Test authentication error categorization."""
        error = aiosmtplib.SMTPAuthenticationError(535, "Authentication failed")
        is_transient, error_type, exc = categorize_smtp_error(error)
        
        assert is_transient is False
        assert error_type == 'authentication_error'
        assert isinstance(exc, SMTPAuthenticationError)
    
    def test_rate_limit_error(self):
        """Test rate limit error categorization."""
        error = Exception("421 Too many connections, rate limit exceeded")
        is_transient, error_type, exc = categorize_smtp_error(error)
        
        assert is_transient is True
        assert error_type == 'rate_limit'
        assert isinstance(exc, SMTPRateLimitError)
    
    def test_mailbox_error(self):
        """Test mailbox error categorization."""
        error = Exception("550 Mailbox does not exist")
        is_transient, error_type, exc = categorize_smtp_error(error)
        
        assert is_transient is False
        assert error_type == 'mailbox_error'
        assert isinstance(exc, SMTPMailboxError)
    
    def test_timeout_error(self):
        """Test timeout error categorization."""
        error = asyncio.TimeoutError()
        is_transient, error_type, exc = categorize_smtp_error(error)
        
        assert is_transient is True
        assert error_type == 'connection_error'
        assert isinstance(exc, SMTPConnectionError)
    
    def test_unknown_error_defaults_to_transient(self):
        """Test unknown errors default to transient."""
        error = Exception("Unknown error XYZ123")
        is_transient, error_type, exc = categorize_smtp_error(error)
        
        assert is_transient is True
        assert error_type == 'unknown'
        assert isinstance(exc, TransientSMTPError)


@pytest.mark.asyncio
class TestAsyncEmailSender:
    """Test AsyncEmailSender class."""
    
    async def test_dry_run_mode(self):
        """Test dry run mode doesn't actually send."""
        config = SMTPServerConfig(
            name="test",
            host="smtp.test.com",
            port=587,
            username="test",
            password="pass"
        )
        pool = SMTPConnectionPool([config])
        sender = AsyncEmailSender(
            connection_pool=pool,
            default_from_email="sender@test.com",
            dry_run=True
        )
        
        result = await sender.send_email(
            recipient="user@test.com",
            subject="Test",
            html_body="<p>Test</p>"
        )
        
        assert result.success is True
        assert result.dry_run is True
        assert result.recipient == "user@test.com"
        assert result.error is None
    
    async def test_send_email_success(self):
        """Test successful email send."""
        # Mock SMTP connection
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(return_value={'response': '250 OK'})
        
        # Mock connection pool
        config = SMTPServerConfig(
            name="test",
            host="smtp.test.com",
            port=587,
            username="test",
            password="pass"
        )
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_success = Mock()
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            default_from_email="sender@test.com"
        )
        
        result = await sender.send_email(
            recipient="user@test.com",
            subject="Test Subject",
            html_body="<p>Test body</p>"
        )
        
        assert result.success is True
        assert result.recipient == "user@test.com"
        assert result.smtp_server == "test"
        assert result.error is None
        
        # Verify connection pool interactions
        pool.acquire.assert_called_once()
        pool.release.assert_called_once()
        pool.record_success.assert_called_once()
    
    async def test_send_email_with_attachments(self):
        """Test sending email with attachments."""
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(return_value={'response': '250 OK'})
        
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_success = Mock()
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            default_from_email="sender@test.com"
        )
        
        attachments = [{
            'data': b'PDF content',
            'filename': 'document.pdf',
            'content_type': 'application/pdf'
        }]
        
        result = await sender.send_email(
            recipient="user@test.com",
            subject="Test with Attachment",
            html_body="<p>See attachment</p>",
            attachments=attachments
        )
        
        assert result.success is True
        mock_conn.send_message.assert_called_once()
    
    async def test_send_email_failure_transient(self):
        """Test transient error handling."""
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(
            side_effect=ConnectionError("Connection timeout")
        )
        
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_failure = Mock()
        
        # Mock retry queue
        retry_queue = Mock()
        retry_queue.add = AsyncMock()
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            retry_queue=retry_queue,
            default_from_email="sender@test.com"
        )
        
        result = await sender.send_email(
            recipient="user@test.com",
            subject="Test",
            html_body="<p>Test</p>"
        )
        
        assert result.success is False
        assert result.is_transient is True
        assert result.error_type == 'connection_error'
        
        # Verify retry queue was called
        retry_queue.add.assert_called_once()
        
        # Verify stats updated
        assert sender.stats['total_failed'] == 1
        assert sender.stats['total_retried'] == 1
    
    async def test_send_email_failure_permanent(self):
        """Test permanent error handling (no retry)."""
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(
            side_effect=aiosmtplib.SMTPAuthenticationError(535, "Auth failed")
        )
        
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_failure = Mock()
        
        retry_queue = Mock()
        retry_queue.add = AsyncMock()
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            retry_queue=retry_queue,
            default_from_email="sender@test.com"
        )
        
        result = await sender.send_email(
            recipient="user@test.com",
            subject="Test",
            html_body="<p>Test</p>"
        )
        
        assert result.success is False
        assert result.is_transient is False
        assert result.error_type == 'authentication_error'
        
        # Verify NO retry for permanent error
        retry_queue.add.assert_not_called()
        assert sender.stats['total_retried'] == 0
    
    async def test_rate_limiting(self):
        """Test rate limiter integration."""
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(return_value={'response': '250 OK'})
        
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_success = Mock()
        
        rate_limiter = RateLimiter(RateLimiterConfig(per_second=10, burst_size=10))
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            rate_limiter=rate_limiter,
            default_from_email="sender@test.com"
        )
        
        # Send 2 emails rapidly
        results = await asyncio.gather(
            sender.send_email("user1@test.com", "Test 1", "<p>1</p>"),
            sender.send_email("user2@test.com", "Test 2", "<p>2</p>")
        )
        
        assert all(r.success for r in results)
        assert len(results) == 2
    
    async def test_bulk_send(self):
        """Test bulk email sending."""
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(return_value={'response': '250 OK'})
        
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_success = Mock()
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            default_from_email="sender@test.com"
        )
        
        recipients = [
            {"email": "user1@test.com", "name": "User1"},
            {"email": "user2@test.com", "name": "User2"},
            {"email": "user3@test.com", "name": "User3"},
        ]
        
        result = await sender.send_bulk(
            recipients=recipients,
            subject_template="Hello {{name}}!",
            html_template="<p>Email to {{email}}</p>",
            concurrency=10
        )
        
        assert isinstance(result, BulkSendResult)
        assert result.total == 3
        assert result.success == 3
        assert result.failed == 0
        assert result.emails_per_second > 0
    
    async def test_bulk_send_with_progress_callback(self):
        """Test bulk send with progress tracking."""
        mock_conn = AsyncMock()
        mock_conn.send_message = AsyncMock(return_value={'response': '250 OK'})
        
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = Mock()
        pool.acquire = AsyncMock(return_value=(mock_conn, config))
        pool.release = AsyncMock()
        pool.record_success = Mock()
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            default_from_email="sender@test.com"
        )
        
        progress_updates = []
        
        async def progress_callback(update: dict):
            progress_updates.append(update)
        
        recipients = [
            {"email": f"user{i}@test.com", "name": f"User{i}"}
            for i in range(5)
        ]
        
        result = await sender.send_bulk(
            recipients=recipients,
            subject_template="Test",
            html_template="<p>Test</p>",
            concurrency=2,
            progress_callback=progress_callback
        )
        
        assert result.total == 5
        assert len(progress_updates) == 5
        assert progress_updates[-1]['percent'] == 100.0
    
    async def test_statistics(self):
        """Test sender statistics."""
        config = SMTPServerConfig(name="test", host="smtp.test.com", port=587)
        pool = SMTPConnectionPool([config])
        
        sender = AsyncEmailSender(
            connection_pool=pool,
            default_from_email="sender@test.com",
            dry_run=True
        )
        
        # Send a few emails
        await sender.send_email("user1@test.com", "Test", "<p>Test</p>")
        await sender.send_email("user2@test.com", "Test", "<p>Test</p>")
        
        stats = sender.get_stats()
        
        assert 'total_sent' in stats
        assert 'total_failed' in stats
        assert 'pool_status' in stats
        assert stats['total_sent'] == 0  # Dry run doesn't increment sent count

