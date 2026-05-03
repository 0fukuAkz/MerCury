"""Dead-letter queue API routes."""

from flask import jsonify

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    session_scope,
)
from ....data.repositories.dead_letter import DeadLetterRepository
from ....services.dead_letter_service import DeadLetterService


@api_bp.route('/dead-letter', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_dead_letters():
    """List dead letter queue items."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        items = service.get_unresolved(limit=100)
        return jsonify({
            'items': [item.to_dict() for item in items],
            'count': len(items),
        })


@api_bp.route('/dead-letter/<int:item_id>/retry', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_retry_dead_letter(item_id):
    """Retry a dead letter item."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        result = service.retry_dead_letter(item_id)
        return jsonify({'success': result is not None})


@api_bp.route('/dead-letter/<int:item_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_discard_dead_letter(item_id):
    """Discard a dead letter item (mark as resolved)."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        result = service.mark_resolved(item_id, "Discarded via UI")
        return jsonify({'success': result is not None})


@api_bp.route('/dead-letter/stats', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_dead_letter_stats():
    """Get dead letter queue statistics."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        stats = service.get_statistics()
        return jsonify(stats)
