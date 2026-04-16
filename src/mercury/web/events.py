"""SocketIO events."""

import logging
import threading
from datetime import datetime, UTC
from flask_socketio import SocketIO, emit
from flask_login import current_user
from ..app_context import get_app_context
from ..data.database import get_session_direct
from ..data.repositories import CampaignRepository
from ..data.models import CampaignStatus
from ..services.campaign_service import CampaignService, CampaignConfig
from ..services.webhook_service import WebhookService
from .extensions import run_async

logger = logging.getLogger(__name__)

# Running service instances keyed by campaign_id so pause/stop can reach them
_active_services: dict[int, CampaignService] = {}

# Shared webhook service instance (loads from env vars once)
_webhook_service = WebhookService()


def _build_config_from_campaign(campaign) -> CampaignConfig:
    """Build a CampaignConfig from a Campaign ORM object."""
    settings = campaign.settings or {}
    subjects = list(campaign.subjects or [])
    subject = subjects[0] if subjects else ""

    # Resolve HTML template from linked Template record
    template_path = ""
    html_content = None
    if campaign.template:
        if campaign.template.html_path:
            template_path = campaign.template.html_path
        elif campaign.template.html_content:
            html_content = campaign.template.html_content

    return CampaignConfig(
        name=campaign.name,
        description=campaign.description or "",
        subject=subject,
        subjects=subjects,
        from_email=campaign.from_email or "",
        from_name=campaign.from_name or "",
        from_emails=settings.get('from_emails') or None,
        from_names=settings.get('from_names') or None,
        reply_to=campaign.reply_to or "",
        template_id=campaign.template_id,
        template_path=template_path,
        html_content=html_content,
        recipients_path=campaign.settings.get("recipients_path", "") if settings else "",
        manual_recipients=settings.get("manual_recipients"),
        links=settings.get("links"),
        placeholders_path=settings.get("placeholders_path", "") if settings else "",
        chunk_size=campaign.chunk_size or 0,
        concurrency=campaign.concurrency or 0,
        rate_per_minute=campaign.rate_per_minute or 0,
        rate_per_hour=campaign.rate_per_hour or 0,
        enable_qr_code=campaign.enable_qr_code or False,
        send_as_image=campaign.convert_to_image or False,
        smtp_rotation=campaign.smtp_rotation_strategy or "weighted",
        dry_run=bool(settings.get("dry_run", False)),
    )


def _run_campaign_thread(campaign_id: int, sio: SocketIO, app):
    """Execute campaign in a background thread using the shared async loop."""

    def _emit(event, data):
        sio.emit(event, data)

    try:
        with app.app_context():
            session = get_session_direct()
            try:
                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                if not campaign:
                    _emit('campaign_error', {'campaign_id': campaign_id, 'error': 'Campaign not found'})
                    return

                config = _build_config_from_campaign(campaign)

                service = CampaignService()
                service.initialize()
                service.load_config(config)
                service._current_campaign = campaign
                _active_services[campaign_id] = service

                # Mark as sending
                campaign.status = CampaignStatus.SENDING
                campaign.started_at = datetime.now(UTC)
                repo.update(campaign)
            finally:
                session.close()

        _emit('campaign_started', {
            'campaign_id': campaign_id,
            'status': 'sending',
            'timestamp': datetime.now(UTC).isoformat(),
        })

        # Notify webhooks
        try:
            run_async(_webhook_service.notify_campaign_started(
                campaign_id=str(campaign_id),
                campaign_name=config.name,
                total_recipients=0  # Will be updated once recipients are loaded
            ))
        except Exception:
            pass  # Best-effort

        # Load recipients
        with app.app_context():
            session = get_session_direct()
            try:
                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                config_snap = _build_config_from_campaign(campaign)
            finally:
                session.close()

        if config_snap.manual_recipients:
            recipients = [{'email': e} for e in config_snap.manual_recipients]
        elif config_snap.recipients_path:
            recipients = list(service.load_recipients_from_csv(
                config_snap.recipients_path,
                email_column=config_snap.email_column,
                validate=config_snap.validate_emails,
                deduplicate=config_snap.deduplicate,
            ))
        else:
            with app.app_context():
                session = get_session_direct()
                try:
                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    if campaign.recipient_list and campaign.recipient_list.file_path:
                        recipients = list(service.load_recipients_from_csv(
                            campaign.recipient_list.file_path,
                            validate=True,
                            deduplicate=True,
                        ))
                    else:
                        recipients = []
                finally:
                    session.close()

        if not recipients:
            with app.app_context():
                session = get_session_direct()
                try:
                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    campaign.status = CampaignStatus.FAILED
                    repo.update(campaign)
                finally:
                    session.close()
            _emit('campaign_error', {'campaign_id': campaign_id, 'error': 'No recipients found'})
            _active_services.pop(campaign_id, None)
            return

        _emit('campaign_progress', {
            'campaign_id': campaign_id,
            'total': len(recipients),
            'sent': 0,
            'failed': 0,
            'status': 'sending',
        })

        async def _progress_cb(progress: dict):
            _emit('campaign_progress', {'campaign_id': campaign_id, **progress})

        stats = run_async(service.run_campaign(recipients, progress_callback=_progress_cb))

        # Determine final status
        final_status = CampaignStatus.COMPLETED
        if not service._running and service._shutdown_event.is_set():
            final_status = CampaignStatus.CANCELLED

        with app.app_context():
            session = get_session_direct()
            try:
                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                campaign.status = final_status
                campaign.completed_at = datetime.now(UTC)
                campaign.sent_count = stats.get('sent', 0)
                campaign.failed_count = stats.get('failed', 0)
                campaign.total_recipients = stats.get('total', len(recipients))
                repo.update(campaign)
            finally:
                session.close()

        _emit('campaign_complete', {
            'campaign_id': campaign_id,
            'status': final_status.value,
            'stats': stats,
        })
        logger.info(f"Campaign {campaign_id} finished: {stats}")

        # Notify webhooks of completion
        try:
            start_ts = stats.get('start_time', '')
            end_ts = stats.get('end_time', '')
            duration = 0.0
            if start_ts and end_ts:
                from datetime import datetime as _dt
                try:
                    duration = (_dt.fromisoformat(end_ts) - _dt.fromisoformat(start_ts)).total_seconds()
                except Exception:
                    pass
            run_async(_webhook_service.notify_campaign_completed(
                campaign_id=str(campaign_id),
                campaign_name=config.name,
                total=stats.get('total', 0),
                success=stats.get('sent', 0),
                failed=stats.get('failed', 0),
                duration_seconds=duration
            ))
        except Exception:
            pass  # Best-effort

    except Exception as exc:
        logger.exception(f"Campaign {campaign_id} crashed: {exc}")
        try:
            with app.app_context():
                session = get_session_direct()
                try:
                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    campaign.status = CampaignStatus.FAILED
                    repo.update(campaign)
                finally:
                    session.close()
        except Exception:
            pass
        _emit('campaign_error', {'campaign_id': campaign_id, 'error': str(exc)})
    finally:
        _active_services.pop(campaign_id, None)


def register_socketio_events(sio: SocketIO):
    """Register WebSocket events."""

    from flask import current_app

    @sio.on('connect')
    def handle_connect():
        """Handle client connection."""
        # Note: current_user relies on Flask-Login which might require request context
        # Flask-SocketIO provides request context for connect event
        if not current_user.is_authenticated:
            return False  # Reject unauthenticated connections

        emit('connected', {'status': 'connected'})
        logger.debug(f"Client connected via WebSocket: {current_user.username}")

    @sio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        logger.debug("Client disconnected")

    @sio.on('start_campaign')
    def handle_start_campaign(data):
        """Start campaign via WebSocket."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get('campaign_id')
        if not campaign_id:
            emit('campaign_error', {'error': 'campaign_id required'})
            return

        if campaign_id in _active_services:
            emit('campaign_error', {'campaign_id': campaign_id, 'error': 'Campaign already running'})
            return

        app = current_app._get_current_object()
        t = threading.Thread(
            target=_run_campaign_thread,
            args=(campaign_id, sio, app),
            daemon=True,
            name=f"campaign-{campaign_id}",
        )
        t.start()
        logger.info(f"Campaign {campaign_id} started via WebSocket by {current_user.username}")

    @sio.on('pause_campaign')
    def handle_pause_campaign(data):
        """Pause campaign."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get('campaign_id')
        svc = _active_services.get(campaign_id)
        if svc:
            svc.pause()

        emit('campaign_paused', {
            'campaign_id': campaign_id,
            'status': 'paused',
            'timestamp': datetime.now(UTC).isoformat()
        })

    @sio.on('resume_campaign')
    def handle_resume_campaign(data):
        """Resume campaign."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get('campaign_id')
        svc = _active_services.get(campaign_id)
        if svc:
            svc.resume()

        emit('campaign_resumed', {
            'campaign_id': campaign_id,
            'status': 'resumed',
            'timestamp': datetime.now(UTC).isoformat()
        })

    @sio.on('stop_campaign')
    def handle_stop_campaign(data):
        """Stop campaign."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get('campaign_id')
        svc = _active_services.get(campaign_id)
        if svc:
            svc.stop()

        emit('campaign_stopped', {
            'campaign_id': campaign_id,
            'status': 'cancelled',
            'timestamp': datetime.now(UTC).isoformat()
        })

def emit_progress(data):
    """Emit progress update to connected clients."""
    ctx = get_app_context()
    ctx.emit_progress(data)

def emit_complete(data):
    """Emit campaign complete event."""
    ctx = get_app_context()
    ctx.emit_complete(data)
