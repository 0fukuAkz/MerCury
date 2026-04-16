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

socketio = SocketIO(
    async_mode='threading',
    cors_allowed_origins=os.environ.get('CORS_ORIGINS', '*')
)

# Single shared asyncio event loop for all background async work.
# All per-campaign coroutines and ad-hoc async calls use this loop via
# asyncio.run_coroutine_threadsafe(), eliminating per-thread event loops.
_background_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()

def _start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()

_background_loop_thread = threading.Thread(
    target=_start_background_loop,
    args=(_background_loop,),
    daemon=True,
    name="mercury-async-loop",
)
_background_loop_thread.start()


def run_async(coro, timeout: float = None):
    """Run a coroutine on the shared background loop and return the result."""
    future = asyncio.run_coroutine_threadsafe(coro, _background_loop)
    return future.result(timeout=timeout)
