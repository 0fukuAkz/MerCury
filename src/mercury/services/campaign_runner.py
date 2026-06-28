"""Support pieces for CampaignService.run_campaign().

Extracted from campaign_service.py to keep the orchestrating class focused
on the send loop itself. Both pieces here are self-contained: the log
writer owns its own queue/event lifecycle, and the pre-flight check
communicates with its caller only via return/raise.
"""

import asyncio
import logging
from typing import List, Optional

from ..data.database import session_scope
from ..data.models import Campaign, EmailLog
from ..data.repositories import CampaignRepository, LogRepository

logger = logging.getLogger(__name__)


class CampaignLogWriter:
    """Background task that batches EmailLog writes off the asyncio loop.

    Sends are produced much faster than individual DB inserts can keep up
    with; batching into groups of ``BATCH_SIZE`` and writing from a thread
    (via ``asyncio.to_thread``) keeps the send loop from blocking on every
    single log row.
    """

    BATCH_SIZE = 100

    def __init__(self):
        self._queue: "asyncio.Queue" = asyncio.Queue()
        self._done = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Spawn the background writer task."""
        self._task = asyncio.create_task(self._run())

    def enqueue(self, log: EmailLog) -> None:
        """Queue a log row for the next batch flush. Non-blocking."""
        self._queue.put_nowait(log)

    async def finish(self) -> None:
        """Signal the writer to drain and stop, and wait for it to finish."""
        # No task means start() was never called (or failed synchronously).
        # The sentinel below would have no consumer, so awaiting _done would
        # block forever — bail out instead of deadlocking the send loop.
        if self._task is None:
            return
        try:
            self._queue.put_nowait(None)
            await self._done.wait()
        except Exception:
            pass

    @staticmethod
    def _flush(logs_to_insert: List[EmailLog], context: str) -> None:
        with session_scope() as local_session:
            try:
                LogRepository(local_session).bulk_create(logs_to_insert)
            except Exception as e:
                logger.warning(f"Failed to bulk save email logs{context}: {e}")

    async def _run(self) -> None:
        try:
            logs_batch: List[EmailLog] = []
            while True:
                try:
                    # Wait up to 1 second for logs
                    log = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                    if log is None:  # Sentinel
                        self._queue.task_done()
                        break
                    logs_batch.append(log)
                    self._queue.task_done()
                except asyncio.TimeoutError:
                    pass

                # Flush if we have reached a good batch size or timed out and have some logs
                if len(logs_batch) >= self.BATCH_SIZE or (logs_batch and self._queue.empty()):
                    batch_to_write = list(logs_batch)
                    logs_batch.clear()
                    # Run sync DB operation in a separate thread so we don't block the async loop
                    await asyncio.to_thread(self._flush, batch_to_write, "")

            # Final flush
            if logs_batch:
                await asyncio.to_thread(self._flush, logs_batch, " (final)")

        except Exception as e:
            logger.error(f"Async DB Log writer task crashed: {e}")
        finally:
            self._done.set()


async def preflight_check(smtp_service, current_campaign: Optional[Campaign]) -> None:
    """Run a pre-flight SMTP health check before sending.

    Raises RuntimeError (and marks the campaign as failed in the DB) if
    every attached SMTP server fails its health check — avoids spinning
    through thousands of recipients only to fail on every single send.
    Caller is responsible for any local state changes (e.g. pausing the
    service) before/after calling this.
    """
    preflight_results = await smtp_service.test_all_connections()
    if not preflight_results or not all(not r.get("success", False) for r in preflight_results):
        return

    failed_hosts = ", ".join(
        f"{r.get('server', 'unknown')} ({r.get('error', 'unknown error')})"
        for r in preflight_results
    )
    error_msg = f"Pre-flight block: All attached SMTP servers failed health check: {failed_hosts}"
    logger.error(error_msg)

    if current_campaign:
        try:
            with session_scope() as session:
                repo = CampaignRepository(session)
                db_cam = repo.get(current_campaign.id)
                if db_cam:
                    db_cam.status = "failed"
                    session.commit()
        except Exception as e:
            logger.error(f"Failed to update campaign state after pre-flight: {e}")

    raise RuntimeError(error_msg)
