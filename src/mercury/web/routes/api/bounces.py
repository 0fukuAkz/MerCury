"""Bounce-tracking API routes."""

from flask import jsonify

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
)
from ....services.bounce_service import BounceService


@api_bp.route("/bounces", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_bounces():
    """List recent bounces."""
    service = BounceService()
    # Get bounce records (stored in service._bounces list)
    bounces = list(service._bounces)[-100:]  # Last 100

    return jsonify({"bounces": [b.to_dict() for b in bounces]})


@api_bp.route("/bounces/stats", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_bounce_stats():
    """Get bounce statistics."""
    service = BounceService()
    stats = service.get_bounce_stats()
    return jsonify(stats)
