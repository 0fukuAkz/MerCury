"""Web route decorators."""

from functools import wraps
from flask import request, jsonify, current_app
from flask_login import current_user

from ..security.auth import require_api_key

def api_key_or_login_required(f):
    """Decorator requiring API key or login for API endpoints."""
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
