"""Flask extensions module."""

import os
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
