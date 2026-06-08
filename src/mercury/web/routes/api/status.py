"""GET /api/status — public health/version endpoint."""

from datetime import datetime, UTC

from flask import jsonify

from . import api_bp


@api_bp.route("/status")
def api_status():
    """Get system status. Public endpoint."""
    return jsonify(
        {
            "status": "ok",
            "timestamp": datetime.now(UTC).isoformat(),
            "version": "2.0.0",
        }
    )
