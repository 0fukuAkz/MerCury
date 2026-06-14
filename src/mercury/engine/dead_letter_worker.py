"""Background worker for retrying dead letters."""

import asyncio
import logging
from typing import Optional

from ..data.database import session_scope
from ..data.repositories.dead_letter import DeadLetterRepository

logger = logging.getLogger("mercury.engine.dead_letter_worker")


class DeadLetterWorker:
    """Worker that periodically retries eligible dead letters in the background."""

    def __init__(self, check_interval_seconds: int = 300, max_retries: int = 3):
        self.check_interval_seconds = check_interval_seconds
        self.max_retries = max_retries
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the background worker."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("DeadLetterWorker started")

    async def stop(self):
        """Stop the background worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DeadLetterWorker stopped")

    async def _process_loop(self):
        """Main loop for checking and retrying dead letters."""
        while self._running:
            try:
                await self._retry_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in dead letter worker loop: {e}")

            # Sleep for the interval
            try:
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break

    async def _retry_batch(self):
        """Retry a batch of unresolved dead letters."""
        from ..web.routes.api.dead_letter import _requeue_item

        with session_scope() as session:
            repo = DeadLetterRepository(session)
            # Fetch up to 50 unresolved dead letters
            items = repo.get_unresolved(limit=50)
            # Filter ones that can be automatically retried
            items_to_retry = [
                item
                for item in items
                if getattr(item, "retry_count", 0) < self.max_retries
                and self._is_retryable(item.error_type)
            ]
            item_ids = [item.id for item in items_to_retry]

        if not item_ids:
            return

        logger.info(f"DeadLetterWorker found {len(item_ids)} messages to auto-retry.")
        for item_id in item_ids:
            if not self._running:
                break
            try:
                # _requeue_item loads the item, sends it synchronously, and updates the db
                result = await asyncio.to_thread(_requeue_item, item_id)
                if result.get("success"):
                    logger.info(f"✅ Auto-requeued dead letter id={item_id} successfully")
                else:
                    logger.warning(
                        f"❌ Auto-requeue failed for id={item_id}: {result.get('error')}"
                    )
            except Exception as e:
                logger.error(f"Failed to auto-process dead letter {item_id}: {e}")

    def _is_retryable(self, error_type: str) -> bool:
        """Determine if an error type should be automatically retried."""
        # Error types are produced by categorize_smtp_error() in async_sender.py.
        # "permanent", "mailbox_error", "invalid_recipient" are not retried.
        retryable_types = {
            "connection_error",   # SMTPServerDisconnected / ConnectionError / TimeoutError
            "rate_limit",         # 4xx rate-limit codes or keyword heuristic
            "transient",          # generic 4xx or keyword heuristic (try again, busy…)
            "unknown",            # default bucket — transient by assumption
            "authentication_error",  # auth errors may be fixed by operators reconfiguring SMTP
        }
        return error_type in retryable_types
