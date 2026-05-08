"""Campaign lifecycle API routes: start (and a home for future stop/pause/resume).

Split out of campaigns.py so the CRUD module stays under ~300 LOC and so any
future lifecycle verbs (stop, pause, resume) have an obvious destination
without re-bloating the CRUD file.
"""

import threading

from flask import jsonify, current_app

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    session_scope,
    CampaignRepository,
)


@api_bp.route('/campaigns/<int:campaign_id>/start', methods=['POST'])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_start_campaign(campaign_id):
    """Start a campaign via REST API (alternative to WebSocket)."""
    from ...events import _run_campaign_thread, _active_services
    from ...extensions import socketio

    if campaign_id in _active_services:
        return jsonify({'error': 'Campaign already running'}), 409

    with session_scope() as session:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404
        if campaign.status not in ('draft', 'scheduled'):
            return jsonify({'error': f'Cannot start campaign with status: {campaign.status}'}), 400

    app = current_app._get_current_object()
    t = threading.Thread(
        target=_run_campaign_thread,
        args=(campaign_id, socketio, app),
        daemon=True,
        name=f"campaign-{campaign_id}",
    )
    t.start()

    return jsonify({
        'success': True,
        'campaign_id': campaign_id,
        'status': 'starting',
    })
