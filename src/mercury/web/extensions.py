"""Flask extensions module."""

import asyncio
import logging
import os
import queue
import threading
from typing import Any, Dict, Tuple
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from flask_login import current_user
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)


# ---- Cross-thread emit bridge ------------------------------------------
#
# Campaign work runs in a `threading.Thread` containing an asyncio loop;
# SocketIO runs in an eventlet greenlet hub. Direct `sio.emit(...)` from
# the asyncio thread silently fails because the eventlet hub doesn't pick
# up calls from foreign threads. Monkey-patching to unify the worlds
# breaks asyncio (deadlocks on threading-backed locks).
#
# Bridge: any thread can put `(event, payload)` tuples onto this stdlib
# queue. A single long-running eventlet greenlet (spawned at SocketIO
# init) drains the queue every ~50ms and emits via the in-hub `sio.emit`.
# stdlib queue.Queue is thread-safe under both threading and eventlet
# without any patching.
_emit_queue: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue(maxsize=10_000)


def queue_emit(event: str, payload: Dict[str, Any]) -> None:
    """Enqueue an event for the SocketIO bridge greenlet to emit.

    Safe to call from any thread. Non-blocking — drops the event if the
    queue is full (which would mean the drain greenlet has stopped, an
    abnormal state worth logging but not crashing the campaign over).
    """
    try:
        _emit_queue.put_nowait((event, payload))
    except queue.Full:
        logger.warning("emit bridge queue full; dropped event %r", event)


def _drain_emit_queue(sio: SocketIO) -> None:
    """Long-running eventlet task: drain the emit queue forever.

    Uses sio.sleep (eventlet-friendly) between idle ticks so other
    greenlets get scheduling. Block on get() with a short timeout so we
    yield even when the queue is empty.
    """
    logger.info("Emit bridge greenlet started")
    while True:
        try:
            event, payload = _emit_queue.get(timeout=0.05)
        except queue.Empty:
            sio.sleep(0.01)  # cooperative yield
            continue
        try:
            sio.emit(event, payload)
        except Exception as e:
            logger.warning("emit bridge: failed to emit %r: %s", event, e)


def start_emit_bridge(sio: SocketIO) -> None:
    """Spawn the bridge greenlet on the SocketIO async backend.

    Idempotent — guarded so multiple init paths can't double-spawn.
    """
    if getattr(sio, "_mercury_bridge_started", False):
        return
    sio._mercury_bridge_started = True
    sio.start_background_task(_drain_emit_queue, sio)


def _get_rate_limit_key():
    """Get rate limit key based on user or IP."""
    # Note: current_user proxy only works within request context
    if current_user and current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()


# Initialize extensions without application instance
# They will be initialized with the app in app_context.py or verify logic
limiter = Limiter(
    key_func=_get_rate_limit_key,
    strategy="fixed-window",  # Default strategy
    storage_uri=os.environ.get("RATE_LIMIT_STORAGE", "memory://"),
)

# SocketIO CORS: default to same-origin only. Operators must explicitly opt
# into cross-origin SocketIO by setting CORS_ORIGINS (comma-separated).
# A bare '*' is still honored for explicit override but is no longer the default.
_cors_env = os.environ.get("CORS_ORIGINS", "").strip()
if not _cors_env:
    _cors_origins: object = []  # disables CORS = same-origin only
elif _cors_env == "*":
    _cors_origins = "*"
else:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

# SocketIO async mode must agree with whichever server is running the app:
#   - run.py launches gunicorn --worker-class eventlet  → 'eventlet'
#   - make dev / socketio.run(allow_unsafe_werkzeug=True) → 'threading'
#   - pytest                                              → 'threading'
# Hard-coding one breaks the other (WebSocket upgrade silently fails when
# async_mode disagrees with the worker class — and tellingly, the broken
# direction is silent: events get queued and never delivered, no error
# logged anywhere, the browser console just shows a stalled long-poll).
#
# We default to 'threading' because it works for every dev / test path
# (Flask dev server, werkzeug, pytest, gunicorn --worker-class sync).
# run.py explicitly sets SOCKETIO_ASYNC_MODE=eventlet on the gunicorn
# subprocess env to opt into the production fast-path. Anyone running
# gunicorn --worker-class eventlet by hand (e.g. in their own deployment
# scripts) needs the same env var. docker-compose.yml sets it; the Dockerfile
# CMD inherits it from there.
_async_mode = os.environ.get("SOCKETIO_ASYNC_MODE", "threading").strip() or "threading"

# Cross-process pub/sub so progress events fan out to clients connected to ANY
# worker/replica. Unset (default) = in-process only, which is correct for the
# single-worker default; set SOCKETIO_MESSAGE_QUEUE=redis://... when scaling the
# web tier past one worker (requires the `redis` package + a shared broker).
#
# Pass the kwarg ONLY when configured: flask-socketio wires a client-manager
# whenever message_queue is present, and an explicit None still diverges from
# omitting it (the in-process emit path the test client relies on changes), so
# the unset/default case must stay byte-identical to "no message_queue at all".
_message_queue = os.environ.get("SOCKETIO_MESSAGE_QUEUE", "").strip() or None
_mq_kwargs: dict[str, str] = {"message_queue": _message_queue} if _message_queue else {}

socketio = SocketIO(
    async_mode=_async_mode,
    cors_allowed_origins=_cors_origins,
    # manage_session=False so Flask-SocketIO uses Flask's session (and
    # therefore Flask-Login's current_user) inside connect handlers.
    # Default True gives SocketIO its own session, which makes
    # current_user.is_authenticated come back False in @sio.on('connect')
    # even for users with valid Flask-Login cookies — causing the connect
    # to be rejected and the client to loop on reconnect.
    manage_session=False,
    **_mq_kwargs,
)

# CSRF protection for browser form POSTs. The api blueprint is exempted
# inside AppContext.initialize() because it's gated by X-API-Key (or session
# cookies on a different code path); the tracking blueprint is exempted
# because tracking pixels / link-click redirects are GETs from external
# clients and don't carry a session token.
csrf = CSRFProtect()

# Single shared asyncio event loop for all background async work.
# Lazily started — importing this module no longer spawns a thread.
_background_loop: asyncio.AbstractEventLoop | None = None
_background_loop_thread: threading.Thread | None = None
_background_loop_lock = threading.Lock()


async def _periodic_smtp_health_check() -> None:
    """Periodically run SMTP health checks on all enabled servers."""
    # Fast initial delay of 30s to let startup stabilize
    await asyncio.sleep(30)
    while True:
        try:
            logger.info("⏰ Triggering periodic background SMTP health checks")
            from ..services.smtp_service import SMTPService
            from ..data.database import session_scope
            from ..data.repositories.smtp import SMTPRepository

            with session_scope() as session:
                repo = SMTPRepository(session)
                servers = repo.get_all()
                configs = [s.get_connection_config() for s in servers if s.is_enabled]

            if configs:
                service = SMTPService()
                service.load_from_config(configs)
                await service.check_all_health()
                logger.info("⏰ Background SMTP health checks completed successfully")
            else:
                logger.debug("⏰ No enabled SMTP servers found for health check")
        except Exception:
            logger.exception("Error in background SMTP health check daemon")
        # Sleep for 5 minutes (300 seconds)
        await asyncio.sleep(300)


def _run_loop_forever(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def start_background_loop() -> asyncio.AbstractEventLoop:
    """Start (or return) the shared background asyncio loop.

    Idempotent and thread-safe; safe to call from create_app() or lazily
    from run_async().
    """
    global _background_loop, _background_loop_thread

    if _background_loop is not None and _background_loop.is_running():
        return _background_loop

    with _background_loop_lock:
        if _background_loop is not None and _background_loop.is_running():
            return _background_loop

        _background_loop = asyncio.new_event_loop()
        _background_loop.create_task(_periodic_smtp_health_check())
        _background_loop_thread = threading.Thread(
            target=_run_loop_forever,
            args=(_background_loop,),
            daemon=True,
            name="mercury-async-loop",
        )
        _background_loop_thread.start()

    return _background_loop


def run_async(coro, timeout: float | None = None):
    """Run a coroutine on the shared background loop and return the result."""
    loop = start_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
