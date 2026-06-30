"""arq worker that executes campaigns off the Redis queue.

Run it with:

    arq mercury.worker.tasks.WorkerSettings

The worker reuses the exact same execution path as the in-process mode
(``_run_campaign_thread``), but injects an ``emit_fn`` that publishes progress
through a Redis-backed SocketIO (the ``SOCKETIO_MESSAGE_QUEUE`` broker) so events
reach clients connected to the web tier. A minimal Flask app supplies the
``app_context`` the execution path expects — we deliberately avoid ``create_app``
so the worker doesn't stand up the web server, emit bridge, or background loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _build_emit_fn() -> Callable[[str, Any], None]:
    """A publish-only SocketIO emit bound to the shared message-queue broker.

    Without a broker the campaign still runs, but progress can't reach web
    clients — warn rather than fail silently.
    """
    mq = os.environ.get("SOCKETIO_MESSAGE_QUEUE")
    if not mq:
        logger.warning(
            "SOCKETIO_MESSAGE_QUEUE is unset; worker progress events will not "
            "reach web clients. Set it to the shared redis:// broker."
        )
        return lambda event, data: None

    from flask_socketio import SocketIO

    client = SocketIO(message_queue=mq)

    def _emit(event: str, data: Any) -> None:
        client.emit(event, data)

    return _emit


async def run_campaign_job(ctx: dict, campaign_id: int) -> None:
    """arq task: execute one campaign on the worker tier."""
    from mercury.web.events import _run_campaign_thread

    app = ctx["flask_app"]
    emit_fn = ctx["emit_fn"]
    logger.info("Worker executing campaign %s", campaign_id)
    # _run_campaign_thread is synchronous (it drives its own async via
    # run_async), so run it off arq's event loop to avoid blocking the worker.
    await asyncio.to_thread(_run_campaign_thread, campaign_id, None, app, emit_fn)


async def _startup(ctx: dict) -> None:
    from flask import Flask

    from mercury.data.database import init_db

    init_db()
    # Minimal app purely for the app_context the execution path wraps DB access
    # in — no web server, no emit bridge, no background loop.
    ctx["flask_app"] = Flask("mercury-worker")
    ctx["emit_fn"] = _build_emit_fn()
    logger.info("Campaign worker ready")


def _redis_settings() -> Any:
    from mercury.worker.queue import _redis_settings as rs

    return rs()


class WorkerSettings:
    """arq entrypoint: ``arq mercury.worker.tasks.WorkerSettings``."""

    functions = [run_campaign_job]
    on_startup = _startup
    redis_settings = _redis_settings()
