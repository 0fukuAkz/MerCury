"""API routes."""

from datetime import datetime, UTC
from flask import Blueprint, jsonify, request, send_file
from sqlalchemy.orm.attributes import flag_modified

from ..decorators import api_key_or_login_required
from ..extensions import limiter, run_async
from ...data.database import get_session_direct
from ...data.repositories import SMTPRepository, TemplateRepository, LogRepository, CampaignRepository
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
    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        campaigns = repo.get_recent(200)
        return jsonify({'campaigns': [c.to_dict() for c in campaigns]})
    finally:
        session.close()

@api_bp.route('/campaigns', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_create_campaign():
    """Create a new email campaign."""
    data = request.get_json(silent=True) or {}
    
    if not data.get('name'):
        return jsonify({'error': 'Campaign name required'}), 400
    
    # Handle rotation arrays (from newline-separated frontend or direct arrays)
    subjects_raw = data.get('subjects') if isinstance(data.get('subjects'), list) else None
    subjects = [s for s in subjects_raw if s and s.strip()] if subjects_raw is not None else None
    from_names = data.get('from_names') if isinstance(data.get('from_names'), list) else None
    from_emails = data.get('from_emails') if isinstance(data.get('from_emails'), list) else None
    templates = data.get('templates') if isinstance(data.get('templates'), list) else None
    links = data.get('links') if isinstance(data.get('links'), list) else None
    manual_recipients = data.get('manual_recipients') if isinstance(data.get('manual_recipients'), list) else None

    config = CampaignConfig(
        name=data.get('name'),
        description=data.get('description', ''),

        # Email content
        subject=data.get('subject', ''),
        subjects=subjects,
        from_email=data.get('from_email', ''),
        from_name=data.get('from_name', ''),
        from_names=from_names,
        from_emails=from_emails,
        reply_to=data.get('reply_to', ''),

        # Templates
        template_id=int(data['template_id']) if data.get('template_id') else None,
        template_path=data.get('template_path', ''),
        templates=templates,

        # Recipients
        recipients_path=data.get('recipients_path', ''),
        manual_recipients=manual_recipients,
        validate_emails=data.get('validate_emails', True),
        deduplicate=data.get('deduplicate', True),
        
        # Sending options
        dry_run=data.get('dry_run', True),
        concurrency=int(data.get('concurrency') or 0),
        rate_per_minute=int(data.get('rate_per_minute', 0)),
        rate_per_hour=int(data.get('rate_per_hour', 0)),
        chunk_size=int(data.get('chunk_size', 0)),
        pause_between_chunks=int(data.get('pause_between_chunks', 0)),
        smtp_rotation=data.get('rotation_strategy', 'weighted'),
        
        # Features
        enable_qr_code=data.get('enable_qr_code', False),
        send_as_image=data.get('send_as_image', False),
        attachment_type=data.get('attachment_type') or None,
        attachment_path=data.get('attachment_path') or None,

        # Links rotation
        links=links,

        # Placeholders
        placeholders_path=data.get('placeholders_path', ''),

        # Tracking
        enable_tracking=data.get('enable_tracking', True),
        track_opens=data.get('track_opens', True),
        track_clicks=data.get('track_clicks', True),
        tracking_base_url=data.get('tracking_base_url', ''),
    )
    
    service = CampaignService()
    service.initialize()
    campaign = service.create_campaign(config)

    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        fresh = repo.get(campaign.id)
        campaign_dict = fresh.to_dict() if fresh else campaign.to_dict()
    finally:
        session.close()

    return jsonify({
        'success': True,
        'campaign': campaign_dict
    })

@api_bp.route('/campaigns/<int:campaign_id>', methods=['GET'])
@api_key_or_login_required
@limiter.limit("60/minute")
def api_get_campaign(campaign_id):
    """Get a single campaign by ID."""
    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404
        return jsonify({'campaign': campaign.to_dict()})
    finally:
        session.close()

@api_bp.route('/campaigns/<int:campaign_id>', methods=['PUT'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_update_campaign(campaign_id):
    """Update an existing campaign (draft/scheduled only)."""
    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404
        if campaign.status not in ('draft', 'scheduled'):
            return jsonify({'error': 'Only draft or scheduled campaigns can be edited'}), 400

        data = request.get_json(silent=True) or {}

        editable = [
            'name', 'description', 'type',
            'from_email', 'from_name', 'reply_to',
            'template_id', 'enable_qr_code', 'convert_to_image',
            'smtp_rotation_strategy', 'auto_failover',
            'chunk_size', 'concurrency', 'rate_per_minute', 'rate_per_hour',
            'pause_between_chunks',
        ]
        int_or_null_fields = {'template_id', 'recipient_list_id'}
        for field in editable:
            if field in data:
                val = data[field]
                # Coerce empty-string to None for integer FK fields
                if field in int_or_null_fields:
                    val = int(val) if val not in (None, '', 'null') else None
                setattr(campaign, field, val)

        # Map send_as_image (form field name) → convert_to_image (column name)
        if 'send_as_image' in data:
            campaign.convert_to_image = bool(data['send_as_image'])

        # subjects list — strip empty entries
        if 'subjects' in data and isinstance(data['subjects'], list):
            campaign.subjects = [s for s in data['subjects'] if s and s.strip()]
        elif 'subject' in data and data['subject'].strip():
            campaign.subjects = [data['subject']]

        # merge settings blob — includes non-column fields like recipients_path, dry_run
        extra = {}
        if data.get('manual_recipients') and isinstance(data['manual_recipients'], list):
            extra['manual_recipients'] = data['manual_recipients']
        # Always write links so an empty list clears previous value
        if 'links' in data and isinstance(data['links'], list):
            extra['links'] = data['links']
        if 'recipients_path' in data and data['recipients_path']:
            extra['recipients_path'] = data['recipients_path']
        if 'dry_run' in data:
            extra['dry_run'] = bool(data['dry_run'])
        if isinstance(data.get('from_emails'), list):
            extra['from_emails'] = data['from_emails']
        if isinstance(data.get('from_names'), list):
            extra['from_names'] = data['from_names']
        if 'template_path' in data:
            extra['template_path'] = data.get('template_path', '')
        if 'templates' in data and isinstance(data['templates'], list):
            extra['templates'] = data['templates']
        for _tracking_field in ('enable_tracking', 'track_opens', 'track_clicks'):
            if _tracking_field in data:
                extra[_tracking_field] = bool(data[_tracking_field])
        if 'tracking_base_url' in data:
            extra['tracking_base_url'] = data.get('tracking_base_url', '')
        # Always merge into settings so rotation fields are persisted every save
        merged = dict(campaign.settings or {})
        merged.update(extra)
        campaign.settings = merged
        # flag_modified ensures SQLAlchemy tracks JSON column changes
        flag_modified(campaign, 'settings')

        repo.update(campaign)
        return jsonify({'success': True, 'campaign': campaign.to_dict()})
    finally:
        session.close()

@api_bp.route('/campaigns/<int:campaign_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_delete_campaign(campaign_id):
    """Delete a campaign. Stops it first if running or paused."""
    from ..events import _active_services

    # Stop the campaign if it's actively running
    svc = _active_services.get(campaign_id)
    if svc:
        svc.stop()

    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404
        # If it was running/paused, mark cancelled before deleting
        if campaign.status in ('sending', 'paused'):
            campaign.status = 'cancelled'
            repo.update(campaign)
        repo.delete(campaign)
        return jsonify({'success': True})
    finally:
        session.close()

@api_bp.route('/campaigns/bulk-delete', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_bulk_delete_campaigns():
    """Bulk delete campaigns by IDs. Stops any running campaigns first."""
    from ..events import _active_services

    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return jsonify({'error': 'List of campaign IDs required'}), 400

    # Stop any active campaigns
    for cid in ids:
        svc = _active_services.get(cid)
        if svc:
            svc.stop()

    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        deleted = 0
        not_found = []
        for cid in ids:
            campaign = repo.get(cid)
            if not campaign:
                not_found.append(cid)
                continue
            if campaign.status in ('sending', 'paused'):
                campaign.status = 'cancelled'
                repo.update(campaign)
            repo.delete(campaign)
            deleted += 1
        return jsonify({'success': True, 'deleted': deleted, 'not_found': not_found})
    finally:
        session.close()

@api_bp.route('/campaigns/<int:campaign_id>/clone', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_clone_campaign(campaign_id):
    """Clone an existing campaign as a new draft."""
    from ...data.models.campaign import Campaign, CampaignStatus
    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        src = repo.get(campaign_id)
        if not src:
            return jsonify({'error': 'Campaign not found'}), 404
        clone = Campaign(
            name=src.name + ' (Copy)',
            description=src.description,
            type=src.type,
            status=CampaignStatus.DRAFT,
            template_id=src.template_id,
            from_email=src.from_email,
            from_name=src.from_name,
            reply_to=src.reply_to,
            subjects=list(src.subjects or []),
            chunk_size=src.chunk_size,
            concurrency=src.concurrency,
            rate_per_minute=src.rate_per_minute,
            rate_per_hour=src.rate_per_hour,
            enable_qr_code=src.enable_qr_code,
            convert_to_image=src.convert_to_image,
            smtp_rotation_strategy=src.smtp_rotation_strategy,
            settings=dict(src.settings or {}),
        )
        clone = repo.create(clone)
        return jsonify({'success': True, 'campaign': clone.to_dict()})
    finally:
        session.close()


@api_bp.route('/campaigns/test-email', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_send_test_email():
    """Send a single test email using the provided campaign settings."""
    from ...services.email_service import EmailService, EmailConfig

    data = request.get_json(silent=True) or {}
    recipient = (data.get('test_recipient') or '').strip().lower()
    if not recipient or '@' not in recipient:
        return jsonify({'success': False, 'error': 'Valid test_recipient is required'}), 400

    # Build a minimal EmailConfig from the form values
    subject = data.get('subject') or '(Test) No subject'
    from_email = data.get('from_email') or ''
    if not from_email:
        return jsonify({'success': False, 'error': 'From Email is required'}), 400

    try:
        # Load SMTP servers
        session = get_session_direct()
        try:
            smtp_repo = SMTPRepository(session)
            smtp_servers = smtp_repo.get_all()
            smtp_configs = [s.get_connection_config() for s in smtp_servers if s.is_enabled]
            if not smtp_configs:
                return jsonify({'success': False, 'error': 'No active SMTP servers configured'}), 400
        finally:
            session.close()

        # Optionally load the template
        template_id = data.get('template_id')
        template_path = data.get('template_path')
        html_body = None
        if template_id:
            session = get_session_direct()
            try:
                trepo = TemplateRepository(session)
                tpl = trepo.get(int(template_id))
                if tpl:
                    html_body = tpl.html_content
            finally:
                session.close()
        elif template_path:
            import os
            if os.path.isfile(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    html_body = f.read()

        # Extract link(s) from form data
        primary_link = (data.get('primary_link') or '').strip()
        links_raw = data.get('links') or data.get('links_list') or []
        if isinstance(links_raw, str):
            links_raw = [l.strip() for l in links_raw.splitlines() if l.strip()]
        link_to_use = primary_link or (links_raw[0] if links_raw else None)

        # Respect campaign tracking/feature toggles (checkboxes send "on" or are absent)
        enable_tracking = data.get('enable_tracking') in (True, 'on', '1', 'true')
        track_opens = data.get('track_opens') in (True, 'on', '1', 'true')
        track_clicks = data.get('track_clicks') in (True, 'on', '1', 'true')

        config = EmailConfig(
            subject=subject,
            from_email=from_email,
            from_name=data.get('from_name', ''),
            reply_to=data.get('reply_to') or None,
            placeholders_path=data.get('placeholders_path') or None,
            enable_tracking=enable_tracking,
            track_opens=track_opens,
            track_clicks=track_clicks,
        )

        smtp_service = SMTPService()
        smtp_service.load_from_config(smtp_configs)

        service = EmailService(smtp_service)
        service.configure(config)
        result = run_async(service.send_single(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=from_email,
            from_name=data.get('from_name', ''),
            reply_to=data.get('reply_to') or None,
            link=link_to_use,
        ))

        if result.success:
            return jsonify({'success': True, 'correlation_id': result.correlation_id})
        else:
            return jsonify({'success': False, 'error': result.error or 'Send failed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/campaigns/<int:campaign_id>/start', methods=['POST'])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_start_campaign(campaign_id):
    """Start a campaign via REST API (alternative to WebSocket)."""
    import threading
    from ..events import _run_campaign_thread, _active_services

    if campaign_id in _active_services:
        return jsonify({'error': 'Campaign already running'}), 409

    session = get_session_direct()
    try:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404
        if campaign.status not in ('draft', 'scheduled'):
            return jsonify({'error': f'Cannot start campaign with status: {campaign.status}'}), 400
    finally:
        session.close()

    from flask import current_app
    from ..extensions import socketio

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
        'status': 'starting'
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
    data = request.get_json(silent=True) or {}
    
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

@api_bp.route('/smtp/test/<int:server_id>', methods=['POST'])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_test_smtp(server_id: int):
    """Test connection to a specific SMTP server by id."""
    session = get_session_direct()
    try:
        repo = SMTPRepository(session)
        server = repo.get(server_id)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404

        servers = repo.get_all()
        service = SMTPService()
        service.load_from_config([s.get_connection_config() for s in servers])

        result = run_async(service.test_connection(server.name))
        return jsonify(result)
    finally:
        session.close()

@api_bp.route('/smtp/<name>', methods=['PUT'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_update_smtp(name):
    """Update an existing SMTP server by name."""
    data = request.get_json(silent=True) or {}
    session = get_session_direct()
    try:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404
        if 'host' in data:
            server.host = data['host']
        if 'port' in data:
            server.port = int(data['port'])
        if 'username' in data:
            server.username = data['username']
        if 'password' in data and data['password']:
            server.password = data['password']
        if 'use_tls' in data:
            server.use_tls = bool(data['use_tls'])
        if 'use_ssl' in data:
            server.use_ssl = bool(data['use_ssl'])
        repo.update(server)
        return jsonify({'success': True, 'server': server.to_dict()})
    finally:
        session.close()

@api_bp.route('/smtp/<name>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_smtp(name):
    """Delete a specific SMTP server by name."""
    session = get_session_direct()
    try:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404
        repo.delete(server)
        return jsonify({'success': True})
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
    data = request.get_json(silent=True) or {}
    
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
    data = request.get_json(silent=True) or {}
    
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


@api_bp.route('/webhooks/<webhook_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_webhook(webhook_id):
    """Delete a registered webhook."""
    service = WebhookService()
    service.unregister_webhook(webhook_id)
    return jsonify({'success': True})


# ============ SCHEDULING API ============

@api_bp.route('/scheduling/jobs', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_scheduled_jobs():
    """List all scheduled jobs."""
    from ...services.scheduler_service import SchedulerService
    
    service = SchedulerService(use_async=False)
    jobs = service.get_all_jobs()
    
    return jsonify({
        'jobs': [j.to_dict() for j in jobs]
    })


@api_bp.route('/scheduling/jobs', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_create_scheduled_job():
    """Create a new scheduled job."""
    from ...services.scheduler_service import SchedulerService
    from datetime import datetime
    import uuid
    
    data = request.get_json(silent=True) or {}
    
    if not data.get('name'):
        return jsonify({'error': 'Job name is required'}), 400
    if not data.get('campaign_id'):
        return jsonify({'error': 'Campaign ID is required'}), 400
    
    service = SchedulerService(use_async=False)
    job_id = data.get('job_id', str(uuid.uuid4()))
    schedule_type = data.get('schedule_type', 'once')
    
    try:
        if schedule_type == 'once':
            run_at = datetime.fromisoformat(data['run_at'])
            job = service.schedule_once(
                job_id=job_id,
                name=data['name'],
                run_at=run_at,
                callback=lambda: None,  # Placeholder - actual execution handled by campaign
                campaign_id=data['campaign_id']
            )
        elif schedule_type == 'recurring':
            if not data.get('cron_expression'):
                return jsonify({'error': 'Cron expression required for recurring jobs'}), 400
            job = service.schedule_recurring(
                job_id=job_id,
                name=data['name'],
                cron_expression=data['cron_expression'],
                callback=lambda: None,
                campaign_id=data['campaign_id'],
                timezone=data.get('timezone') or None,
                max_runs=int(data['max_runs']) if data.get('max_runs') else None,
            )
        elif schedule_type == 'interval':
            if not data.get('interval_seconds'):
                return jsonify({'error': 'Interval seconds required'}), 400
            job = service.schedule_interval(
                job_id=job_id,
                name=data['name'],
                interval_seconds=int(data['interval_seconds']),
                callback=lambda: None,
                campaign_id=data['campaign_id'],
                timezone=data.get('timezone') or None,
                max_runs=int(data['max_runs']) if data.get('max_runs') else None,
            )
        else:
            return jsonify({'error': f'Invalid schedule type: {schedule_type}'}), 400
        
        return jsonify({
            'success': True,
            'job': job.to_dict()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/scheduling/jobs/<job_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_cancel_scheduled_job(job_id):
    """Cancel a scheduled job."""
    from ...services.scheduler_service import SchedulerService
    
    service = SchedulerService(use_async=False)
    success = service.cancel_job(job_id)
    
    return jsonify({'success': success})


@api_bp.route('/scheduling/jobs/<job_id>/pause', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_pause_scheduled_job(job_id):
    """Pause a scheduled job."""
    from ...services.scheduler_service import SchedulerService
    
    service = SchedulerService(use_async=False)
    service.pause_job(job_id)
    
    return jsonify({'success': True})


@api_bp.route('/scheduling/jobs/<job_id>/resume', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_resume_scheduled_job(job_id):
    """Resume a paused job."""
    from ...services.scheduler_service import SchedulerService
    
    service = SchedulerService(use_async=False)
    service.resume_job(job_id)
    
    return jsonify({'success': True})


# ============ BOUNCE API ============

@api_bp.route('/bounces', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_bounces():
    """List recent bounces."""
    from ...services.bounce_service import BounceService
    
    service = BounceService()
    # Get bounce records (stored in service._bounces list)
    bounces = list(service._bounces)[-100:]  # Last 100
    
    return jsonify({
        'bounces': [b.to_dict() for b in bounces]
    })


@api_bp.route('/bounces/stats', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_bounce_stats():
    """Get bounce statistics."""
    from ...services.bounce_service import BounceService
    
    service = BounceService()
    stats = service.get_bounce_stats()
    
    return jsonify(stats)


# ============ RECIPIENTS FILE API ============

def _recipients_dir() -> str:
    """Return the absolute path to the data/recipients directory, creating it if needed."""
    import os
    base = os.path.join(os.getcwd(), 'data', 'recipients')
    os.makedirs(base, exist_ok=True)
    return base


def _safe_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal."""
    import os, re
    name = os.path.basename(name)
    name = re.sub(r'[^\w\s.\-]', '_', name)
    return name or 'upload.csv'


@api_bp.route('/recipients', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_recipient_files():
    """List all recipient list files in data/recipients/."""
    import os
    base = _recipients_dir()
    files = []
    for fname in sorted(os.listdir(base)):
        fpath = os.path.join(base, fname)
        if os.path.isfile(fpath) and fname.lower().endswith(('.csv', '.txt')):
            stat = os.stat(fpath)
            files.append({
                'filename': fname,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            })
    return jsonify({'files': files, 'count': len(files)})


@api_bp.route('/recipients/upload', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_upload_recipients():
    """Upload a CSV/TXT recipient file with optional validation and deduplication."""
    import os, csv, io, re

    uploaded = request.files.get('file')
    if not uploaded:
        return jsonify({'error': 'No file uploaded'}), 400

    validate = request.form.get('validate', 'true').lower() in ('true', '1', 'yes')
    deduplicate = request.form.get('deduplicate', 'true').lower() in ('true', '1', 'yes')

    raw = uploaded.stream.read().decode('utf-8', errors='replace')
    filename = _safe_filename(uploaded.filename or 'upload.csv')

    # Parse as CSV; fall back to plain-text (one email per line)
    email_rgx = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    rows = []
    fieldnames = []
    try:
        reader = csv.DictReader(io.StringIO(raw))
        if reader.fieldnames and any(f.lower().strip() == 'email' for f in reader.fieldnames):
            fieldnames = [f.strip() for f in reader.fieldnames]
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items()})
        else:
            raise ValueError("no email column")
    except Exception:
        # Plain-text fallback — one email per line
        fieldnames = ['email']
        rows = [{'email': line.strip()} for line in raw.splitlines() if line.strip() and '@' in line]

    total_raw = len(rows)

    # Validate email format
    invalid_count = 0
    if validate:
        valid_rows = []
        for r in rows:
            email = r.get('email', '').lower().strip()
            if email_rgx.match(email):
                r['email'] = email
                valid_rows.append(r)
            else:
                invalid_count += 1
        rows = valid_rows

    # Deduplicate
    dup_count = 0
    if deduplicate:
        seen = set()
        deduped = []
        for r in rows:
            key = r.get('email', '').lower()
            if key not in seen:
                seen.add(key)
                deduped.append(r)
            else:
                dup_count += 1
        rows = deduped

    # Write processed file
    base = _recipients_dir()
    dest = os.path.join(base, filename)
    with open(dest, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return jsonify({
        'success': True,
        'filename': filename,
        'total_raw': total_raw,
        'invalid_removed': invalid_count,
        'duplicates_removed': dup_count,
        'saved': len(rows),
    })


@api_bp.route('/recipients/<filename>/preview', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_preview_recipients(filename: str):
    """Return the first N rows of a recipient file."""
    import os, csv, io

    filename = _safe_filename(filename)
    fpath = os.path.join(_recipients_dir(), filename)
    if not os.path.isfile(fpath):
        return jsonify({'error': 'File not found'}), 404

    limit = min(int(request.args.get('limit', 20)), 200)
    rows = []
    fieldnames = []
    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for i, row in enumerate(reader):
            if i >= limit:
                break
            rows.append(dict(row))

    return jsonify({'filename': filename, 'columns': fieldnames, 'rows': rows, 'count': len(rows)})


@api_bp.route('/recipients/<filename>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_recipient_file(filename: str):
    """Delete a recipient list file."""
    import os

    filename = _safe_filename(filename)
    fpath = os.path.join(_recipients_dir(), filename)
    if not os.path.isfile(fpath):
        return jsonify({'error': 'File not found'}), 404

    os.remove(fpath)
    return jsonify({'success': True, 'filename': filename})


# ============ DEAD LETTER API ============

@api_bp.route('/dead-letter', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_dead_letters():
    """List dead letter queue items."""
    from ...services.dead_letter_service import DeadLetterService
    from ...data.repositories.dead_letter import DeadLetterRepository
    
    session = get_session_direct()
    try:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        items = service.get_unresolved(limit=100)
        
        return jsonify({
            'items': [item.to_dict() for item in items],
            'count': len(items)
        })
    finally:
        session.close()


@api_bp.route('/dead-letter/<int:item_id>/retry', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_retry_dead_letter(item_id):
    """Retry a dead letter item."""
    from ...services.dead_letter_service import DeadLetterService
    from ...data.repositories.dead_letter import DeadLetterRepository
    
    session = get_session_direct()
    try:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        result = service.retry_dead_letter(item_id)
        
        return jsonify({'success': result is not None})
    finally:
        session.close()


@api_bp.route('/dead-letter/<int:item_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_discard_dead_letter(item_id):
    """Discard a dead letter item (mark as resolved)."""
    from ...services.dead_letter_service import DeadLetterService
    from ...data.repositories.dead_letter import DeadLetterRepository
    
    session = get_session_direct()
    try:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        result = service.mark_resolved(item_id, "Discarded via UI")
        
        return jsonify({'success': result is not None})
    finally:
        session.close()


@api_bp.route('/dead-letter/stats', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_dead_letter_stats():
    """Get dead letter queue statistics."""
    from ...services.dead_letter_service import DeadLetterService
    from ...data.repositories.dead_letter import DeadLetterRepository
    
    session = get_session_direct()
    try:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        stats = service.get_statistics()
        
        return jsonify(stats)
    finally:
        session.close()

