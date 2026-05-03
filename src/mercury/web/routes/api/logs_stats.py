"""Email log and statistics API routes."""

from flask import jsonify

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    get_session_direct,
    LogRepository,
)


@api_bp.route('/logs/success')
@api_key_or_login_required
@limiter.limit("30/minute")
def api_success_logs():
    """Get success logs."""
    session = get_session_direct()
    try:
        repo = LogRepository(session)
        logs = repo.get_recent_success(limit=100)
        return jsonify({'emails': [l.recipient_email for l in logs]})
    finally:
        session.close()


@api_bp.route('/logs/failed')
@api_key_or_login_required
@limiter.limit("30/minute")
def api_failed_logs():
    """Get failed logs."""
    session = get_session_direct()
    try:
        repo = LogRepository(session)
        logs = repo.get_recent_failed(limit=100)

        failures = [
            f"{l.recipient_email}: {l.error_message} ({l.failed_at.isoformat()})"
            for l in logs
        ]
        return jsonify({'failures': failures})
    finally:
        session.close()


@api_bp.route('/stats')
@api_key_or_login_required
@limiter.limit("30/minute")
def api_stats():
    """Get overall sending statistics."""
    session = get_session_direct()
    try:
        repo = LogRepository(session)
        stats = repo.get_global_stats()
        return jsonify(stats)
    finally:
        session.close()
