"""Campaign CRUD + bulk + clone API routes.

Lifecycle (start/stop/pause/resume) lives in ``campaigns_lifecycle``.
Test-email lives in ``campaigns_testing``. Tests patch this module's
``CampaignRepository`` / ``CampaignService`` bindings, so those names
must remain re-exported into this module's namespace via ``from .``.
"""

from flask import jsonify, request
from sqlalchemy.orm.attributes import flag_modified

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    session_scope,
    CampaignRepository,
    CampaignService,
    CampaignConfig,
)


@api_bp.route('/campaigns', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_campaigns():
    """List all email campaigns."""
    with session_scope() as session:
        repo = CampaignRepository(session)
        campaigns = repo.get_recent(200)
        return jsonify({'campaigns': [c.to_dict() for c in campaigns]})


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

    with session_scope() as session:
        repo = CampaignRepository(session)
        fresh = repo.get(campaign.id)
        campaign_dict = fresh.to_dict() if fresh else campaign.to_dict()

    return jsonify({
        'success': True,
        'campaign': campaign_dict,
    })


@api_bp.route('/campaigns/<int:campaign_id>', methods=['GET'])
@api_key_or_login_required
@limiter.limit("60/minute")
def api_get_campaign(campaign_id):
    """Get a single campaign by ID."""
    with session_scope() as session:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            return jsonify({'error': 'Campaign not found'}), 404
        return jsonify({'campaign': campaign.to_dict()})


@api_bp.route('/campaigns/<int:campaign_id>', methods=['PUT'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_update_campaign(campaign_id):
    """Update an existing campaign (draft/scheduled only)."""
    with session_scope() as session:
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


@api_bp.route('/campaigns/<int:campaign_id>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_delete_campaign(campaign_id):
    """Delete a campaign. Stops it first if running or paused."""
    from ...events import _active_services

    # Stop the campaign if it's actively running
    svc = _active_services.get(campaign_id)
    if svc:
        svc.stop()

    with session_scope() as session:
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


@api_bp.route('/campaigns/bulk-delete', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_bulk_delete_campaigns():
    """Bulk delete campaigns by IDs. Stops any running campaigns first."""
    from ...events import _active_services

    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return jsonify({'error': 'List of campaign IDs required'}), 400

    # Stop any active campaigns
    for cid in ids:
        svc = _active_services.get(cid)
        if svc:
            svc.stop()

    with session_scope() as session:
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


@api_bp.route('/campaigns/<int:campaign_id>/clone', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_clone_campaign(campaign_id):
    """Clone an existing campaign as a new draft."""
    from ....data.models.campaign import Campaign, CampaignStatus
    with session_scope() as session:
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
