"""Enqueue campaign jobs onto the arq (Redis) task queue.

Imported by the web tier. When ``CAMPAIGN_EXECUTION_MODE=worker``,
``handle_start_campaign`` pushes a job here instead of spawning an in-process
thread; a separate worker process (``mercury.worker.tasks``) consumes it. arq is
imported lazily inside the functions so the default in-process path needs no arq
dependency at import time.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def worker_mode_enabled() -> bool:
    """True when campaign execution should be enqueued to the worker tier."""
    return os.environ.get("CAMPAIGN_EXECUTION_MODE", "inprocess").strip().lower() == "worker"


def queue_redis_url() -> str:
    """Redis DSN for the task queue.

    Falls back to the SocketIO broker, then a local default — the worker tier is
    expected to share Redis with the rest of the stack.
    """
    return (
        os.environ.get("CAMPAIGN_QUEUE_REDIS")
        or os.environ.get("SOCKETIO_MESSAGE_QUEUE")
        or "redis://localhost:6379/0"
    )


def _redis_settings() -> Any:
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(queue_redis_url())


async def enqueue_campaign(campaign_id: int) -> Optional[str]:
    """Push a ``run_campaign_job`` onto the queue; return its job id (or None).

    Raises on connection failure so the caller can fall back to in-process
    execution rather than dropping the campaign.
    """
    from arq import create_pool

    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job("run_campaign_job", campaign_id)
        return job.job_id if job else None
    finally:
        await pool.close()
