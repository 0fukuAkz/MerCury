"""Tests for the campaign_runner support module.

Covers the two pieces extracted from CampaignService.run_campaign():

* ``CampaignLogWriter`` — the background EmailLog batch writer. We verify
  it flushes everything enqueued, batches at ``BATCH_SIZE``, swallows DB
  errors without crashing the send loop, and never deadlocks if ``finish()``
  is called without ``start()``.
* ``preflight_check`` — the all-SMTP-servers-down guard. We verify it
  raises (and marks the campaign failed) only when *every* server fails,
  and otherwise lets the send proceed.

Both ``session_scope`` and the repositories are mocked, so these tests
touch no real database and no real SMTP.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mercury.services.campaign_runner import CampaignLogWriter, preflight_check


# --------------------------------------------------------------------------
# CampaignLogWriter
# --------------------------------------------------------------------------


def _collect_flushed(mock_repo):
    """Flatten every list passed to bulk_create across all flush calls."""
    flushed = []
    for call in mock_repo.return_value.bulk_create.call_args_list:
        flushed.extend(call.args[0])
    return flushed


class TestCampaignLogWriter:
    async def test_flushes_all_enqueued_logs(self):
        """Every enqueued row must reach bulk_create exactly once, in order."""
        with patch("mercury.services.campaign_runner.session_scope"), patch(
            "mercury.services.campaign_runner.LogRepository"
        ) as MockRepo:
            writer = CampaignLogWriter()
            writer.start()

            logs = [MagicMock(name=f"log{i}") for i in range(5)]
            for log in logs:
                writer.enqueue(log)

            await asyncio.wait_for(writer.finish(), timeout=5)

            assert _collect_flushed(MockRepo) == logs

    async def test_batches_at_batch_size(self):
        """A full batch is flushed in a single bulk_create call."""
        with patch("mercury.services.campaign_runner.session_scope"), patch(
            "mercury.services.campaign_runner.LogRepository"
        ) as MockRepo:
            writer = CampaignLogWriter()
            writer.start()

            logs = [MagicMock(name=f"log{i}") for i in range(CampaignLogWriter.BATCH_SIZE)]
            for log in logs:
                writer.enqueue(log)

            await asyncio.wait_for(writer.finish(), timeout=5)

            batch_sizes = [
                len(call.args[0]) for call in MockRepo.return_value.bulk_create.call_args_list
            ]
            # All rows accounted for, and at least one flush was a full batch.
            assert sum(batch_sizes) == CampaignLogWriter.BATCH_SIZE
            assert CampaignLogWriter.BATCH_SIZE in batch_sizes

    async def test_swallows_flush_errors_and_still_finishes(self):
        """A DB failure inside flush must not crash the writer task."""
        with patch("mercury.services.campaign_runner.session_scope"), patch(
            "mercury.services.campaign_runner.LogRepository"
        ) as MockRepo:
            MockRepo.return_value.bulk_create.side_effect = RuntimeError("db down")

            writer = CampaignLogWriter()
            writer.start()
            writer.enqueue(MagicMock())

            # Should return cleanly despite the flush raising internally.
            await asyncio.wait_for(writer.finish(), timeout=5)
            assert writer._done.is_set()

    async def test_finish_without_start_does_not_deadlock(self):
        """finish() before start() must return instead of awaiting forever."""
        writer = CampaignLogWriter()
        # No start(): there is no consumer for the sentinel, so a naive
        # implementation would block on _done forever.
        await asyncio.wait_for(writer.finish(), timeout=2)

    async def test_enqueue_is_non_blocking_before_start(self):
        """enqueue() must accept rows even before the consumer task runs."""
        writer = CampaignLogWriter()
        writer.enqueue(MagicMock())  # must not raise or block
        assert writer._queue.qsize() == 1


# --------------------------------------------------------------------------
# preflight_check
# --------------------------------------------------------------------------


def _smtp_returning(results):
    smtp = MagicMock()
    smtp.test_all_connections = AsyncMock(return_value=results)
    return smtp


class TestPreflightCheck:
    async def test_raises_and_marks_failed_when_all_servers_fail(self):
        smtp = _smtp_returning(
            [
                {"success": False, "server": "h1", "error": "refused"},
                {"success": False, "server": "h2", "error": "timeout"},
            ]
        )
        campaign = MagicMock(id=42)

        with patch("mercury.services.campaign_runner.session_scope") as mock_scope, patch(
            "mercury.services.campaign_runner.CampaignRepository"
        ) as MockRepo:
            session = mock_scope.return_value.__enter__.return_value
            db_cam = MagicMock()
            MockRepo.return_value.get.return_value = db_cam

            with pytest.raises(RuntimeError, match="Pre-flight block"):
                await preflight_check(smtp, campaign)

            MockRepo.return_value.get.assert_called_once_with(42)
            assert db_cam.status == "failed"
            session.commit.assert_called_once()

    async def test_proceeds_when_at_least_one_server_succeeds(self):
        smtp = _smtp_returning(
            [
                {"success": True, "server": "h1"},
                {"success": False, "server": "h2", "error": "x"},
            ]
        )
        with patch("mercury.services.campaign_runner.session_scope") as mock_scope:
            await preflight_check(smtp, MagicMock(id=1))  # must not raise
            mock_scope.assert_not_called()  # no DB writes on the happy path

    async def test_proceeds_when_no_servers_were_tested(self):
        smtp = _smtp_returning([])
        with patch("mercury.services.campaign_runner.session_scope") as mock_scope:
            await preflight_check(smtp, MagicMock(id=1))  # empty == nothing to block on
            mock_scope.assert_not_called()

    async def test_raises_without_db_write_when_no_campaign(self):
        smtp = _smtp_returning([{"success": False, "server": "h", "error": "e"}])
        with patch("mercury.services.campaign_runner.session_scope") as mock_scope:
            with pytest.raises(RuntimeError, match="Pre-flight block"):
                await preflight_check(smtp, None)
            mock_scope.assert_not_called()

    async def test_db_failure_while_marking_is_swallowed_but_still_raises(self):
        """If marking the campaign failed errors, we still raise the block."""
        smtp = _smtp_returning([{"success": False, "server": "h", "error": "e"}])
        with patch(
            "mercury.services.campaign_runner.session_scope",
            side_effect=RuntimeError("db gone"),
        ), patch("mercury.services.campaign_runner.CampaignRepository"):
            with pytest.raises(RuntimeError, match="Pre-flight block"):
                await preflight_check(smtp, MagicMock(id=7))
