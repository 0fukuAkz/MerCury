import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, UTC
from email.message import EmailMessage
import aiosmtplib

from mercury.engine.async_sender import (
    AsyncEmailSender,
    EmailResult,
    BulkSendResult,
    categorize_smtp_error,
    SMTPConnectionError,
    SMTPAuthenticationError,
    SMTPRateLimitError,
    SMTPMailboxError,
    PermanentSMTPError,
    send_email_async,
    send_bulk_emails_async,
)
from mercury.engine.connection_pool import SMTPServerConfig, SMTPConnectionPool


@pytest.fixture
def mock_pool():
    pool = AsyncMock(spec=SMTPConnectionPool)
    pool.acquire.return_value = (AsyncMock(), MagicMock(spec=SMTPServerConfig, name="test_server"))
    return pool


@pytest.fixture
def async_sender(mock_pool):
    sender = AsyncEmailSender(connection_pool=mock_pool)
    return sender


class TestErrorCategorizationExtended:
    """Extended tests for error categorization."""

    def test_categorize_connection_errors(self):
        err = aiosmtplib.SMTPServerDisconnected("Disconnected")
        transient, type_, exc = categorize_smtp_error(err)
        assert transient is True
        assert type_ == "connection_error"
        assert isinstance(exc, SMTPConnectionError)

    def test_categorize_auth_errors(self):
        err = aiosmtplib.SMTPAuthenticationError(535, "Auth failed")
        transient, type_, exc = categorize_smtp_error(err)
        assert transient is False
        assert type_ == "authentication_error"
        assert isinstance(exc, SMTPAuthenticationError)

    def test_categorize_rate_limit(self):
        err = Exception("450 4.7.1 Rate limit exceeded")
        transient, type_, exc = categorize_smtp_error(err)
        assert transient is True
        assert type_ == "rate_limit"
        assert isinstance(exc, SMTPRateLimitError)

    def test_categorize_mailbox_error(self):
        err = Exception("550 5.1.1 User unknown")
        transient, type_, exc = categorize_smtp_error(err)
        assert transient is False
        assert type_ == "mailbox_error"
        assert isinstance(exc, SMTPMailboxError)

    def test_categorize_permanent_error(self):
        err = Exception("554 5.7.1 Message rejected as spam")
        transient, type_, exc = categorize_smtp_error(err)
        assert transient is False
        assert type_ == "permanent"
        assert isinstance(exc, PermanentSMTPError)


@pytest.mark.asyncio
class TestAsyncSenderExtended:
    """Extended tests for AsyncEmailSender."""

    async def test_send_email_dry_run(self, mock_pool):
        sender = AsyncEmailSender(mock_pool, dry_run=True)
        res = await sender.send_email("to@test.com", "Subj", "Body")
        assert res.dry_run is True
        assert res.success is True
        mock_pool.acquire.assert_not_called()

    async def test_send_email_with_attachments_and_headers(self, async_sender, mock_pool):
        conn = AsyncMock()
        conn.send_message.return_value = {}
        mock_pool.acquire.return_value = (conn, MagicMock(name="s1"))

        attachments = [{"filename": "test.txt", "data": b"hello", "content_type": "text/plain"}]
        headers = {"X-Custom": "Value"}

        res = await async_sender.send_email(
            "to@test.com", "Subj", "Body", attachments=attachments, headers=headers
        )

        assert res.success is True
        conn.send_message.assert_called_once()
        msg = conn.send_message.call_args[0][0]
        assert isinstance(msg, EmailMessage)
        assert msg["X-Custom"] == "Value"
        assert len(msg.get_payload()) > 1  # multipart

    async def test_send_email_rate_limited_locally(self, async_sender):
        limiter = AsyncMock()
        limiter.acquire.return_value = False
        async_sender.rate_limiter = limiter

        res = await async_sender.send_email("to@test.com", "S", "B")
        assert res.success is False
        assert res.error_type == "rate_limit"

    async def test_send_email_transient_failure_retry(self, async_sender, mock_pool):
        # Setup connection failure
        conn = AsyncMock()
        conn.send_message.side_effect = aiosmtplib.SMTPServerDisconnected("Boom")
        mock_pool.acquire.return_value = (conn, MagicMock(name="s1"))

        # Setup retry queue
        async_sender.retry_queue = AsyncMock()

        res = await async_sender.send_email("to@test.com", "S", "B")

        assert res.success is False
        assert res.is_transient is True
        async_sender.retry_queue.add.assert_called_once()
        assert async_sender.stats["total_retried"] == 1

    async def test_send_bulk_concurrency(self, async_sender):
        # Mock send_email to take some time
        async def slow_send(*args, **kwargs):
            await asyncio.sleep(0.01)
            return EmailResult(True, "t", "id", datetime.now(UTC))

        async_sender.send_email = AsyncMock(side_effect=slow_send)

        recipients = [{"email": f"user{i}@test.com", "name": f"User {i}"} for i in range(10)]
        progress = AsyncMock()

        res = await async_sender.send_bulk(
            recipients,
            "Subj {{name}}",
            "Body {{name}}",
            from_email="me@test.com",
            concurrency=2,
            progress_callback=progress,
        )

        assert res.total == 10
        assert res.success == 10
        assert async_sender.send_email.call_count == 10
        assert progress.call_count == 10

    async def test_convenience_function_bulk(self):
        with patch("mercury.engine.async_sender.SMTPConnectionPool") as MockPool, patch(
            "mercury.engine.async_sender.AsyncEmailSender"
        ) as MockSender:
            mock_pool_inst = MockPool.return_value
            mock_pool_inst.close_all = AsyncMock()

            mock_sender_inst = MockSender.return_value
            mock_sender_inst.send_bulk = AsyncMock(
                return_value=BulkSendResult(
                    1, 1, 0, 1.0, 1.0, datetime.now(UTC), datetime.now(UTC), []
                )
            )

            smtp_config = {"host": "localhost"}
            res = await send_bulk_emails_async(
                [{"email": "t@t.com"}], "S", "B", smtp_config, "f@f.com"
            )

            assert res["success"] == 1
            mock_pool_inst.close_all.assert_called_once()

    async def test_convenience_function_single(self):
        with patch("mercury.engine.async_sender.AsyncConnectionPool") as MockPool, patch(
            "mercury.engine.async_sender.SMTPServerConfig"
        ) as MockConfig:
            pool_inst = MockPool.return_value
            pool_inst.initialize = AsyncMock()
            pool_inst.close_all = AsyncMock()

            conn = AsyncMock()
            # connect returns None usually
            conn.connect.return_value = None
            conn.send_message.return_value = {"response": "OK"}

            pool_inst.get_connection = AsyncMock(return_value=conn)

            smtp_config = {"host": "localhost"}
            res = await send_email_async("t@t.com", "S", "B", smtp_config, "f@f.com")

            assert res["success"] is True
            conn.send_message.assert_called_once()
