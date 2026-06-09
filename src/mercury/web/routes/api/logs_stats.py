"""Email log and statistics API routes."""

from flask import jsonify

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    session_scope,
    LogRepository,
)


@api_bp.route("/logs/success")
@api_key_or_login_required
@limiter.limit("30/minute")
def api_success_logs():
    """Get success logs."""
    with session_scope() as session:
        repo = LogRepository(session)
        logs = repo.get_recent_success(limit=100)
        return jsonify({
            "emails": [
                {
                    "email": log.recipient_email,
                    "time": log.sent_at.isoformat() if log.sent_at else None,
                    "opens": log.open_count,
                    "clicks": log.click_count,
                    "status": log.status
                }
                for log in logs
            ]
        })


@api_bp.route("/logs/failed")
@api_key_or_login_required
@limiter.limit("30/minute")
def api_failed_logs():
    """Get failed logs."""
    with session_scope() as session:
        repo = LogRepository(session)
        logs = repo.get_recent_failed(limit=100)
        return jsonify({
            "failures": [
                {
                    "email": log.recipient_email,
                    "error": log.error_message or "Unknown error",
                    "time": log.failed_at.isoformat() if log.failed_at else None,
                    "status": log.status
                }
                for log in logs
            ]
        })


@api_bp.route("/stats")
@api_key_or_login_required
@limiter.limit("30/minute")
def api_stats():
    """Get overall sending statistics."""
    with session_scope() as session:
        repo = LogRepository(session)
        stats = repo.get_global_stats()
        return jsonify(stats)
