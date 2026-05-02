"""Web route decorators."""

from functools import wraps
from flask import request, jsonify
from flask_login import current_user

from ..security.auth import require_api_key


def api_key_required(f):
    """Decorator requiring a valid API key — rejects session-only callers.

    Use for automation-only endpoints (webhooks, machine-to-machine integrations)
    that must NOT accept browser session cookies as auth.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or not require_api_key(api_key):
            return jsonify({'error': 'Valid X-API-Key header required'}), 401
        return f(*args, **kwargs)
    return decorated_function


def api_key_or_login_required(f):
    """Decorator accepting either a valid API key OR an authenticated session.

    Use for endpoints that serve both browser dashboard users and API clients
    (most ``/api/*`` routes). For automation-only endpoints, prefer
    ``api_key_required`` to deny session-cookie callers.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for API key in header
        api_key = request.headers.get('X-API-Key')
        if api_key and require_api_key(api_key):
            return f(*args, **kwargs)

        # Fall back to login check
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401

        return f(*args, **kwargs)
    return decorated_function
