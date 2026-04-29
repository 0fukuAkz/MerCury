"""Flask extensions module."""

import asyncio
import os
import threading
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO
from flask_login import current_user

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
    strategy="fixed-window", # Default strategy
    storage_uri=os.environ.get('RATE_LIMIT_STORAGE', 'memory://')
)

# SocketIO CORS: default to same-origin only. Operators must explicitly opt
# into cross-origin SocketIO by setting CORS_ORIGINS (comma-separated).
# A bare '*' is still honored for explicit override but is no longer the default.
_cors_env = os.environ.get('CORS_ORIGINS', '').strip()
if not _cors_env:
    _cors_origins: object = []  # disables CORS = same-origin only
elif _cors_env == '*':
    _cors_origins = '*'
else:
    _cors_origins = [o.strip() for o in _cors_env.split(',') if o.strip()]

socketio = SocketIO(
    async_mode='threading',
    cors_allowed_origins=_cors_origins,
)

# Single shared asyncio event loop for all background async work.
# Lazily started — importing this module no longer spawns a thread.
_background_loop: asyncio.AbstractEventLoop | None = None
_background_loop_thread: threading.Thread | None = None
_background_loop_lock = threading.Lock()


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
