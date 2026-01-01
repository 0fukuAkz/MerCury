"""API routes."""

import asyncio
from datetime import datetime, UTC
from flask import Blueprint, jsonify, request
from flask_login import current_user

from ..decorators import api_key_or_login_required
from ..extensions import limiter
from ...data.database import get_session_direct
from ...data.repositories import SMTPRepository, TemplateRepository, LogRepository
from ...services.campaign_service import CampaignService, CampaignConfig
from ...services.smtp_service import SMTPService
from ...features.template_engine import TemplateEngine
from ...services.webhook_service import WebhookService, WebhookEvent

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/status')
def api_status():
    """
    Get system status.
    Public endpoint.
    """
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now(UTC).isoformat(),
        'version': '2.0.0'
    })

@api_bp.route('/campaigns', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_campaigns():
    """List all email campaigns."""
    service = CampaignService()
    # service.initialize() # Check if initialize is needed? It was called in app.py
    # app.py: service.initialize()
    service.initialize()
    campaigns = service.list_campaigns()
    
    return jsonify({
        'campaigns': [c.to_dict() for c in campaigns]
    })

@api_bp.route('/campaigns', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_create_campaign():
    """Create a new email campaign."""
    data = request.json
    
    if not data.get('name'):
        return jsonify({'error': 'Campaign name required'}), 400
    
    config = CampaignConfig(
        name=data.get('name'),
        description=data.get('description', ''),
        subject=data.get('subject', ''),
        from_email=data.get('from_email', ''),
        from_name=data.get('from_name', ''),
        template_path=data.get('template_path', ''),
        recipients_path=data.get('recipients_path', ''),
        dry_run=data.get('dry_run', True)
    )
    
    service = CampaignService()
    service.initialize()
    campaign = service.create_campaign(config)
    
    return jsonify({
        'success': True,
        'campaign': campaign.to_dict()
    })

@api_bp.route('/smtp', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_smtp():
    """List all configured SMTP servers."""
    session = get_session_direct()
    try:
        repo = SMTPRepository(session)
        servers = repo.get_all()
        return jsonify({
            'servers': [s.to_dict() for s in servers]
        })
    finally:
        session.close()

@api_bp.route('/smtp', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_add_smtp():
    """Add a new SMTP server configuration."""
    data = request.json
    
    if not data.get('host'):
        return jsonify({'error': 'Host required'}), 400
    
    service = SMTPService()
    server = service.add_server(
        name=data.get('name', data.get('host')),
        host=data['host'],
        port=data.get('port', 587),
        username=data.get('username', ''),
        password=data.get('password', ''),
        use_tls=data.get('use_tls', True)
    )
    
    return jsonify({
        'success': True,
        'server': server.to_dict()
    })

@api_bp.route('/smtp/test/<name>', methods=['POST'])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_test_smtp(name):
    """Test connection to a specific SMTP server."""
    session = get_session_direct()
    try:
        repo = SMTPRepository(session)
        servers = repo.get_all()
        
        service = SMTPService()
        service.load_from_config([s.get_connection_config() for s in servers])
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(service.test_connection(name))
        finally:
            loop.close()
        
        return jsonify(result)
    finally:
        session.close()

@api_bp.route('/templates', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_templates():
    """List email templates."""
    session = get_session_direct()
    try:
        repo = TemplateRepository(session)
        templates = repo.get_active()
        return jsonify({
            'templates': [t.to_dict() for t in templates]
        })
    finally:
        session.close()

@api_bp.route('/templates/preview', methods=['POST'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_preview_template():
    """Preview template with sample data."""
    data = request.json
    
    engine = TemplateEngine(html_content=data.get('html', ''))
    preview = engine.preview(
        recipient=data.get('recipient', 'test@example.com'),
        extra_placeholders=data.get('placeholders', {})
    )
    
    return jsonify({
        'html': preview,
        'placeholders': engine.get_used_placeholders()
    })

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

@api_bp.route('/webhooks', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_webhooks():
    """List registered webhooks."""
    service = WebhookService()
    webhooks = service.get_webhooks()
    
    return jsonify({
        'webhooks': [w.to_dict() for w in webhooks]
    })

@api_bp.route('/webhooks', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_register_webhook():
    """Register new webhook."""
    data = request.json
    
    if not data.get('url'):
        return jsonify({'error': 'Webhook URL required'}), 400
    
    service = WebhookService()
    
    # Parse events
    events = None
    if data.get('events'):
        events = []
        for e in data['events']:
            try:
                events.append(WebhookEvent(e))
            except ValueError:
                pass
    
    webhook = service.register_webhook(
        url=data['url'],
        events=events,
        secret=data.get('secret')
    )
    
    return jsonify({
        'success': True,
        'webhook': webhook.to_dict()
    })
