"""Health check routes."""

from flask import Blueprint, jsonify
from sqlalchemy import text
from ...data.database import get_engine, session_scope
from ...data.repositories import SMTPRepository
import shutil

health_bp = Blueprint('health', __name__)

@health_bp.route('/ready')
def readiness_check():
    """
    Kubernetes readiness probe.
    
    Checks if the application is ready to handle traffic.
    Returns 200 if database connection is available.
    """
    # Check if app can handle requests
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({'ready': True}), 200
    except Exception:
        return jsonify({'ready': False}), 503

@health_bp.route('/live')
def liveness_check():
    """
    Kubernetes liveness probe.
    
    Checks if the application process is alive and responding.
    Always returns 200 if the application is running.
    """
    return jsonify({'alive': True}), 200

@health_bp.route('/health/detailed')
def detailed_health_check():
    """
    Detailed health check for all components.
    
    Checks:
    - Database
    - SMTP configurations
    - Disk space
    """
    status = {
        'status': 'healthy',
        'components': {
            'database': {'status': 'healthy'},
            'smtp': {'status': 'healthy'},
            'disk': {'status': 'healthy'}
        }
    }
    
    # Check Database
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        status['status'] = 'degraded'
        status['components']['database'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
        
    # Check SMTP (can we read config?)
    try:
        with session_scope() as session:
            repo = SMTPRepository(session)
            servers = repo.get_active()
            status['components']['smtp']['count'] = len(servers)
    except Exception as e:
        # Don't fail overall health if just SMTP list fails, but mark degraded
        status['status'] = 'degraded'
        status['components']['smtp'] = {
            'status': 'unknown',
            'error': str(e)
        }

    # Check Disk Space
    try:
        total, used, free = shutil.disk_usage("/")
        status['components']['disk']['free_gb'] = round(free / (1024**3), 2)
        
        if free < 1 * (1024**3): # Less than 1GB
            status['status'] = 'degraded'
            status['components']['disk']['status'] = 'warning'
    except Exception as e:
        status['components']['disk'] = {
            'status': 'unknown',
            'error': str(e)
        }
        
    from flask_login import current_user
    from flask import request
    from ...security.auth import validate_api_key

    is_authed = False
    if current_user and current_user.is_authenticated:
        is_authed = True
    elif request.headers.get('X-API-Key') and validate_api_key(request.headers.get('X-API-Key')):
        is_authed = True

    if not is_authed:
        # Strip details for unauthenticated users
        return jsonify({'status': status['status']}), 200

    return jsonify(status), 200
