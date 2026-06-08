"""Tests for the DeadLetterWorker background worker."""

import asyncio
from unittest.mock import MagicMock, patch
import pytest

from mercury.engine.dead_letter_worker import DeadLetterWorker


@pytest.mark.asyncio
class TestDeadLetterWorker:
    """Test Suite for DeadLetterWorker."""

    async def test_start_and_stop(self):
        """Test starting and stopping the worker."""
        worker = DeadLetterWorker(check_interval_seconds=1, max_retries=3)
        assert worker._running is False
        assert worker._task is None

        # Start
        await worker.start()
        assert worker._running is True
        assert worker._task is not None
        assert isinstance(worker._task, asyncio.Task)

        # Calling start again should be a no-op
        old_task = worker._task
        await worker.start()
        assert worker._task is old_task

        # Stop
        await worker.stop()
        assert worker._running is False
        # Task cancellation is clean
        await asyncio.sleep(0.01)

    async def test_process_loop_exception_safe(self):
        """Test process loop handles exception without breaking."""
        worker = DeadLetterWorker(check_interval_seconds=10, max_retries=3)
        worker._running = True

        # First we test raising an Exception (which is handled and continues),
        # then raising CancelledError inside _retry_batch (which should hit line 48 and break),
        # and then raising CancelledError inside the sleep (which should hit line 55 and break).
        with patch.object(worker, "_retry_batch") as mock_retry:
            mock_retry.side_effect = [
                RuntimeError("Transient database issue"),
                asyncio.CancelledError(),
            ]
            await worker._process_loop()
            assert mock_retry.call_count == 2

        # Reset worker running state to test CancelledError in sleep
        worker2 = DeadLetterWorker(check_interval_seconds=10, max_retries=3)
        worker2._running = True
        with patch.object(worker2, "_retry_batch") as mock_retry2, patch(
            "asyncio.sleep", side_effect=asyncio.CancelledError()
        ):
            await worker2._process_loop()
            mock_retry2.assert_called_once()

    async def test_is_retryable(self):
        """Test _is_retryable classification."""
        worker = DeadLetterWorker()
        assert worker._is_retryable("connection_error") is True
        assert worker._is_retryable("timeout_error") is True
        assert worker._is_retryable("rate_limit_error") is True
        assert worker._is_retryable("transient_error") is True
        assert worker._is_retryable("authentication_error") is True
        assert worker._is_retryable("permanent_error") is False
        assert worker._is_retryable("invalid_recipient") is False
        assert worker._is_retryable("") is False

    @patch("mercury.engine.dead_letter_worker.session_scope")
    @patch("mercury.engine.dead_letter_worker.DeadLetterRepository")
    async def test_retry_batch_no_items(self, mock_repo_class, mock_session_scope):
        """Test _retry_batch when no dead letters exist."""
        mock_repo = MagicMock()
        mock_repo.get_unresolved.return_value = []
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        worker = DeadLetterWorker()
        # Should return early
        await worker._retry_batch()
        mock_repo.get_unresolved.assert_called_once_with(limit=50)

    @patch("mercury.engine.dead_letter_worker.session_scope")
    @patch("mercury.engine.dead_letter_worker.DeadLetterRepository")
    @patch("mercury.web.routes.api.dead_letter._requeue_item")
    async def test_retry_batch_filtering(
        self, mock_requeue_item, mock_repo_class, mock_session_scope
    ):
        """Test that _retry_batch filters retry count and error types correctly."""
        # 1. exceeds max retries (3)
        item_exceeds = MagicMock()
        item_exceeds.id = 1
        item_exceeds.retry_count = 3
        item_exceeds.error_type = "connection_error"

        # 2. permanent error type (not retryable)
        item_permanent = MagicMock()
        item_permanent.id = 2
        item_permanent.retry_count = 0
        item_permanent.error_type = "permanent_error"

        # 3. retryable
        item_retryable = MagicMock()
        item_retryable.id = 3
        item_retryable.retry_count = 1
        item_retryable.error_type = "timeout_error"

        mock_repo = MagicMock()
        mock_repo.get_unresolved.return_value = [item_exceeds, item_permanent, item_retryable]
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        # Mock requeue success
        mock_requeue_item.return_value = {"success": True}

        worker = DeadLetterWorker()
        worker._running = True
        await worker._retry_batch()

        # Only item_retryable (id=3) should be processed
        mock_requeue_item.assert_called_once_with(3)

    @patch("mercury.engine.dead_letter_worker.session_scope")
    @patch("mercury.engine.dead_letter_worker.DeadLetterRepository")
    @patch("mercury.web.routes.api.dead_letter._requeue_item")
    async def test_retry_batch_requeue_failures_and_errors(
        self, mock_requeue_item, mock_repo_class, mock_session_scope
    ):
        """Test _retry_batch handles requeue failures and unexpected exceptions robustly."""
        item1 = MagicMock()
        item1.id = 10
        item1.retry_count = 0
        item1.error_type = "connection_error"

        item2 = MagicMock()
        item2.id = 20
        item2.retry_count = 0
        item2.error_type = "connection_error"

        item3 = MagicMock()
        item3.id = 30
        item3.retry_count = 0
        item3.error_type = "connection_error"

        mock_repo = MagicMock()
        mock_repo.get_unresolved.return_value = [item1, item2, item3]
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        # mock_requeue_item:
        # id=10: fails with {"success": False}
        # id=20: throws exception
        # id=30: succeeds with {"success": True}
        mock_requeue_item.side_effect = [
            {"success": False, "error": "SMTP server down"},
            RuntimeError("Unexpected error"),
            {"success": True},
        ]

        worker = DeadLetterWorker()
        worker._running = True
        await worker._retry_batch()

        # All three items are processed regardless of previous steps failing
        assert mock_requeue_item.call_count == 3
        mock_requeue_item.assert_any_call(10)
        mock_requeue_item.assert_any_call(20)
        mock_requeue_item.assert_any_call(30)

    @patch("mercury.engine.dead_letter_worker.session_scope")
    @patch("mercury.engine.dead_letter_worker.DeadLetterRepository")
    @patch("mercury.web.routes.api.dead_letter._requeue_item")
    async def test_retry_batch_respects_stop(
        self, mock_requeue_item, mock_repo_class, mock_session_scope
    ):
        """Test that _retry_batch loop stops mid-run if worker is stopped."""
        item1 = MagicMock()
        item1.id = 1
        item1.retry_count = 0
        item1.error_type = "connection_error"

        item2 = MagicMock()
        item2.id = 2
        item2.retry_count = 0
        item2.error_type = "connection_error"

        mock_repo = MagicMock()
        mock_repo.get_unresolved.return_value = [item1, item2]
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        # When resolving the first item, we stop the worker
        worker = DeadLetterWorker()
        worker._running = True

        def mock_requeue(item_id):
            worker._running = False  # Stopped
            return {"success": True}

        mock_requeue_item.side_effect = mock_requeue

        await worker._retry_batch()

        # Only item 1 is processed, loop stops because worker._running is False
        mock_requeue_item.assert_called_once_with(1)
