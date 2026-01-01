"""Health check routes."""

from flask import Blueprint, jsonify
from sqlalchemy import text
from ...data.database import get_engine

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
