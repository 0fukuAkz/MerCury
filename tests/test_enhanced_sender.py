"""Tests for EnhancedAsyncEmailSender."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, ANY
from datetime import datetime, UTC

from unified_sender.engine.enhanced_sender import (
    EnhancedAsyncEmailSender,
    EmailResult,
    BulkSendResult
)
from unified_sender.engine.error_recovery import (
    ErrorRecoveryManager,
    ErrorRecoveryDecision,
    RecoveryStrategy
)
from unified_sender.engine.error_aggregator import ErrorAggregator
from unified_sender.services.dead_letter_service import DeadLetterService
from unified_sender.engine.connection_pool import SMTPConnectionPool


@pytest.fixture
def mock_connection_pool():
    pool = Mock(spec=SMTPConnectionPool)
    # Default acquire returns a mock connection and config
    pool.acquire = AsyncMock(return_value=(AsyncMock(), Mock(name="smtp_config")))
    pool.release = AsyncMock()
    return pool


@pytest.fixture
def mock_dead_letter_service():
    return Mock(spec=DeadLetterService)


@pytest.fixture
def mock_recovery_manager():
    return Mock(spec=ErrorRecoveryManager)


@pytest.fixture
def enhanced_sender(mock_connection_pool, mock_dead_letter_service, mock_recovery_manager):
    return EnhancedAsyncEmailSender(
        connection_pool=mock_connection_pool,
        dead_letter_service=mock_dead_letter_service,
        error_recovery_manager=mock_recovery_manager,
        default_from_email="sender@example.com"
    )


@pytest.mark.asyncio
class TestEnhancedSender:

    async def test_initialization(self, mock_connection_pool):
        """Test initialization sets up components."""
        sender = EnhancedAsyncEmailSender(mock_connection_pool)
        assert sender.connection_pool == mock_connection_pool
        assert isinstance(sender.error_recovery, ErrorRecoveryManager)
        assert sender.dead_letter_service is None
        assert sender._current_aggregator is None

    async def test_send_email_success_no_recovery_needed(self, enhanced_sender):
        """Test successful send without needing recovery."""
        # Setup the mock on the instance, not class patch, to be safer
        with patch.object(enhanced_sender, 'send_email', new_callable=AsyncMock) as mock_super_send:
            mock_super_send.return_value = EmailResult(
                success=True,
                recipient="test@example.com",
                correlation_id="123",
                timestamp=datetime.now(UTC),
                smtp_server="primary"
            )
            
            # Must patch the PARENT class method if we are calling super().send_email
            # But EnhancedSender calls super().send_email.
            # patching unified_sender.engine.async_sender.AsyncEmailSender.send_email works IF the method is awaited.
            
            # Let's try patching the actual class method again but ensure return_value is correct.
            pass

    async def test_send_email_success_no_recovery_needed_v2(self, enhanced_sender):
         # Redoing the test with proper class patching
         with patch('unified_sender.engine.async_sender.AsyncEmailSender.send_email', new_callable=AsyncMock) as mock_super_send:
            mock_super_send.return_value = EmailResult(
                success=True,
                recipient="test@example.com",
                correlation_id="123",
                timestamp=datetime.now(UTC),
                smtp_server="primary"
            )
            
            result = await enhanced_sender.send_email_with_recovery(
                recipient="test@example.com",
                subject="Test",
                html_body="<p>Body</p>",
                correlation_id="123" 
            )
            
            assert result.success is True
            assert result.smtp_server == "primary"
            enhanced_sender.error_recovery.clear_tracking.assert_called_with("123")

    async def test_recovery_switch_server(self, enhanced_sender):
        """Test recovery by switching server."""
        # Use side_effect with an async-compatible iterable
        with patch('unified_sender.engine.async_sender.AsyncEmailSender.send_email', new_callable=AsyncMock) as mock_super_send:
            
            fail_result = EmailResult(
                success=False,
                recipient="test@example.com",
                correlation_id="123",
                timestamp=datetime.now(UTC),
                error="Connection failed",
                is_transient=True,
                smtp_server="primary"
            )
            success_result = EmailResult(
                success=True,
                recipient="test@example.com",
                correlation_id="123",
                timestamp=datetime.now(UTC),
                smtp_server="backup"
            )
            
            mock_super_send.side_effect = [fail_result, success_result]
            
            enhanced_sender.error_recovery.decide_recovery.side_effect = [
                ErrorRecoveryDecision(strategy=RecoveryStrategy.SWITCH_SERVER, should_retry=True, alternative_smtp="backup")
            ]
            
            result = await enhanced_sender.send_email_with_recovery(
                recipient="test@example.com", subject="Test", html_body="Body",
                correlation_id="123", preferred_smtp="primary"
            )
            
            assert result.success is True
            assert result.smtp_server == "backup"
            assert mock_super_send.call_count == 2

    async def test_recovery_delay_retry(self, enhanced_sender):
        """Test recovery with delay."""
        with patch('unified_sender.engine.async_sender.AsyncEmailSender.send_email', new_callable=AsyncMock) as mock_super_send:
            fail_result = EmailResult(success=False, recipient="test", correlation_id="1", timestamp=datetime.now(UTC), error="Busy", is_transient=True)
            success_result = EmailResult(success=True, recipient="test", correlation_id="1", timestamp=datetime.now(UTC))
            
            mock_super_send.side_effect = [fail_result, success_result]
            
            enhanced_sender.error_recovery.decide_recovery.return_value = ErrorRecoveryDecision(
                strategy=RecoveryStrategy.DELAY_RETRY,
                should_retry=True,
                retry_delay=0.01  # Small delay for test
            )
            
            # Patch sleep to not actually wait but verify it was called
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                await enhanced_sender.send_email_with_recovery(
                    recipient="test@example.com",
                    subject="Test",
                    html_body="Body"
                )
                
                mock_sleep.assert_awaited_once_with(0.01)

    async def test_recovery_dead_letter(self, enhanced_sender):
        """Test moving to dead letter queue."""
        with patch('unified_sender.engine.async_sender.AsyncEmailSender.send_email', new_callable=AsyncMock) as mock_super_send:
            fail_result = EmailResult(
                success=False, 
                recipient="test@example.com", 
                correlation_id="123", 
                timestamp=datetime.now(UTC), 
                error="Permanent failure", 
                is_transient=False,
                error_type="permanent"
            )
            
            mock_super_send.return_value = fail_result
            
            enhanced_sender.error_recovery.decide_recovery.return_value = ErrorRecoveryDecision(
                strategy=RecoveryStrategy.DEAD_LETTER,
                should_retry=False
            )
            
            result = await enhanced_sender.send_email_with_recovery(
                recipient="test@example.com",
                subject="Test",
                html_body="Body",
                correlation_id="123",
                campaign_id=1
            )
            
            assert result.success is False
            enhanced_sender.dead_letter_service.add_dead_letter.assert_called_once()
            
            # Verify args
            call_kwargs = enhanced_sender.dead_letter_service.add_dead_letter.call_args[1]
            assert call_kwargs['recipient'] == "test@example.com"
            assert call_kwargs['campaign_id'] == 1
            assert call_kwargs['error_type'] == "permanent"

    async def test_recovery_exhausted(self, enhanced_sender):
        """Test exhaustion of retry attempts."""
        with patch('unified_sender.engine.async_sender.AsyncEmailSender.send_email', new_callable=AsyncMock) as mock_super_send:
            fail_result = EmailResult(success=False, recipient="test", correlation_id="1", timestamp=datetime.now(UTC), error="Timeout", is_transient=True)
            mock_super_send.return_value = fail_result
            
            # Always suggest retry
            enhanced_sender.error_recovery.decide_recovery.return_value = ErrorRecoveryDecision(
                strategy=RecoveryStrategy.DELAY_RETRY,
                should_retry=True,
                retry_delay=0
            )
            
            result = await enhanced_sender.send_email_with_recovery(
                recipient="test@example.com",
                subject="Test",
                html_body="Body",
                max_recovery_attempts=2
            )
            
            assert result.success is False
            assert result.error_type == "recovery_exhausted"
            assert mock_super_send.call_count == 2

    async def test_unexpected_exception_in_recovery(self, enhanced_sender):
        """Test handling of unexpected exception during recovery logic."""
        with patch('unified_sender.engine.async_sender.AsyncEmailSender.send_email', new_callable=AsyncMock) as mock_super_send:
            mock_super_send.side_effect = Exception("Critical Error")
            
            with pytest.raises(Exception) as exc:
                await enhanced_sender.send_email_with_recovery(
                    recipient="test@example.com",
                    subject="Test",
                    html_body="Body"
                )
            assert "Critical Error" in str(exc.value)

    async def test_bulk_send_with_aggregation(self, enhanced_sender):
        """Test bulk sending with error aggregation."""
        # Setup results: 1 success, 1 failure
        success_result = EmailResult(success=True, recipient="user1@example.com", correlation_id="1", timestamp=datetime.now(UTC))
        fail_result = EmailResult(
            success=False, 
            recipient="user2@example.com", 
            correlation_id="2", 
            timestamp=datetime.now(UTC), 
            error="Rate Limit", 
            is_transient=True,
            smtp_server="smtp1"
        )
        
        # Mock send_email_with_recovery since that's what bulk uses
        with patch.object(enhanced_sender, 'send_email_with_recovery') as mock_send:
            mock_send.side_effect = [success_result, fail_result]
            
            recipients = [
                {"email": "user1@example.com", "name": "User1"},
                {"email": "user2@example.com", "name": "User2"}
            ]
            
            bulk_result, aggregator = await enhanced_sender.send_bulk_with_aggregation(
                recipients=recipients,
                subject_template="Hello {{name}}",
                html_template="Body",
                campaign_id=1,
                concurrency=2
            )
            
            assert bulk_result.total == 2
            assert bulk_result.success == 1
            assert bulk_result.failed == 1
            
            # Check aggregator
            summary = aggregator.get_summary()
            assert summary.total_errors == 1
            assert summary.groups[0].smtp_servers == ["smtp1"]
            assert "user2@example.com" in summary.groups[0].recipients

    async def test_bulk_send_unexpected_exception(self, enhanced_sender):
        """Test bulk sending handles unexpected exceptions."""
        with patch.object(enhanced_sender, 'send_email_with_recovery') as mock_send:
            mock_send.side_effect = Exception("Unexpected Crash")
            
            recipients = [{"email": "user1@example.com"}]
            
            bulk_result, aggregator = await enhanced_sender.send_bulk_with_aggregation(
                recipients=recipients,
                subject_template="Subject",
                html_template="Body"
            )
            
            assert bulk_result.failed == 1
            assert bulk_result.results[0].error_type == "unexpected_exception"
            assert "Unexpected Crash" in bulk_result.results[0].error
