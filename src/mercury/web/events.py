"""SocketIO events."""

import logging
import threading
from datetime import datetime, UTC
from flask_socketio import SocketIO, emit
from flask_login import current_user
from ..app_context import get_app_context
from ..data.database import session_scope, get_session_direct
from ..data.repositories import CampaignRepository
from ..data.models import CampaignStatus
from ..services.campaign_service import CampaignService, CampaignConfig
from ..services.webhook_service import WebhookService
from .extensions import run_async

logger = logging.getLogger(__name__)

# Running service instances keyed by campaign_id so pause/stop can reach them
_active_services: dict[int, CampaignService] = {}
_active_services_lock = threading.Lock()

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

    # Fallback: custom template path stored in settings
    if not template_path and not html_content:
        template_path = settings.get("template_path", "")

    return CampaignConfig(
        name=campaign.name,
        description=campaign.description or "",
        subject=subject,
        subjects=subjects,
        from_email=campaign.from_email or "",
        from_name=campaign.from_name or "",
        from_emails=settings.get("from_emails") or None,
        from_names=settings.get("from_names") or None,
        reply_to=campaign.reply_to or "",
        template_id=campaign.template_id,
        template_path=template_path,
        html_content=html_content,
        templates=settings.get("templates") or None,
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
        attachment_ids=[
            int(x) for x in (settings.get("attachment_ids") or []) if str(x).strip().isdigit()
        ],
        convert_attachment=bool(settings.get("convert_attachment", False)),
        attachment_convert_to=settings.get("attachment_convert_to") or None,
        logo_attachment_id=(
            int(settings["logo_attachment_id"])
            if str(settings.get("logo_attachment_id") or "").strip().isdigit()
            else None
        ),
        auto_company_logo=bool(settings.get("auto_company_logo", False)),
        hide_from_email_header=bool(settings.get("hide_from_email_header", False)),
        validate_emails=bool(settings.get("validate_emails", True)),
        deduplicate=bool(settings.get("deduplicate", True)),
        pause_between_chunks=campaign.pause_between_chunks or 0,
        placeholders=dict(campaign.placeholders or {}),
        smtp_rotation=campaign.smtp_rotation_strategy or "weighted",
        smtp_server_id=settings.get("smtp_server_id"),
        dry_run=bool(settings.get("dry_run", False)),
        enable_tracking=bool(settings.get("enable_tracking", True)),
        track_opens=bool(settings.get("track_opens", True)),
        track_clicks=bool(settings.get("track_clicks", True)),
        tracking_base_url=settings.get("tracking_base_url") or "",
        mail_priority=settings.get("mail_priority", "3"),
    )


def _run_campaign_thread(campaign_id: int, sio: SocketIO, app):
    """Execute campaign in a background thread.

    Emits go through the cross-thread bridge queue (see extensions.py:
    queue_emit / start_emit_bridge). The bridge greenlet drains the queue
    on the SocketIO hub and emits there. This avoids the eventlet/asyncio
    thread-affinity conflict that direct sio.emit (or start_background_task
    from a non-eventlet thread) ran into.
    """
    from .extensions import queue_emit

    def _emit(event, data):
        queue_emit(event, data)

    try:
        with app.app_context():
            with session_scope() as session:

                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                if not campaign:
                    _emit(
                        "campaign_error",
                        {"campaign_id": campaign_id, "error": "Campaign not found"},
                    )
                    return

                config = _build_config_from_campaign(campaign)

                service = CampaignService()
                service.initialize()
                service.load_config(config)
                service._current_campaign = campaign
                with _active_services_lock:
                    _active_services[campaign_id] = service

                # Mark as sending
                campaign.status = CampaignStatus.SENDING
                campaign.started_at = datetime.now(UTC)
                repo.update(campaign)

        # Note: 'campaign_started' was already emitted synchronously by the
        # WebSocket handler as a request-acknowledgment; the thread continues
        # the work but doesn't re-emit. 'campaign_progress' below will signal
        # that recipients are loaded and sending is actually underway.

        # Notify webhooks
        try:
            run_async(
                _webhook_service.notify_campaign_started(
                    campaign_id=str(campaign_id),
                    campaign_name=config.name,
                    total_recipients=0,  # Will be updated once recipients are loaded
                )
            )
        except Exception:
            pass  # Best-effort

        # Load recipients
        with app.app_context():
            with session_scope() as session:

                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                config_snap = _build_config_from_campaign(campaign)

        # Resolution precedence:
        #   1. manual_recipients          (UI textarea / API explicit list)
        #   2. linked recipient_list      (explicit DB foreign key — the
        #      "I chose this list from the dropdown" path)
        #   3. recipients_path snapshot   (legacy / YAML path)
        #
        # Previously (2) and (3) were swapped, which meant a campaign with
        # both an attached RecipientList AND a stale recipients_path in
        # settings would silently load the stale path. Operators uploaded
        # a fresh list via the UI, saw the snapshot file get loaded
        # instead, and reported "campaigns not using uploaded recipient
        # list even when chosen."
        recipients = []
        if config_snap.manual_recipients:
            recipients = [{"email": e} for e in config_snap.manual_recipients]
        else:
            linked_list_path = None
            with app.app_context():
                with session_scope() as session:

                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    if campaign and campaign.recipient_list and campaign.recipient_list.file_path:
                        linked_list_path = campaign.recipient_list.file_path

            if linked_list_path:
                if config_snap.recipients_path and config_snap.recipients_path != linked_list_path:
                    logger.warning(
                        "Campaign %s has both a linked recipient_list (%s) AND a "
                        "stale recipients_path (%s); using the linked list. Clean "
                        "up the settings.recipients_path to silence this.",
                        campaign_id,
                        linked_list_path,
                        config_snap.recipients_path,
                    )
                recipients = list(
                    service.load_recipients_from_csv(
                        linked_list_path,
                        validate=True,
                        deduplicate=True,
                    )
                )
            elif config_snap.recipients_path:
                recipients = list(
                    service.load_recipients_from_csv(
                        config_snap.recipients_path,
                        email_column=config_snap.email_column,
                        validate=config_snap.validate_emails,
                        deduplicate=config_snap.deduplicate,
                    )
                )

        if not recipients:
            with app.app_context():
                with session_scope() as session:

                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    campaign.status = CampaignStatus.FAILED
                    repo.update(campaign)
            _emit("campaign_error", {"campaign_id": campaign_id, "error": "No recipients found"})
            with _active_services_lock:
                _active_services.pop(campaign_id, None)
            return

        _emit(
            "campaign_progress",
            {
                "campaign_id": campaign_id,
                "total": len(recipients),
                "sent": 0,
                "failed": 0,
                "status": "sending",
            },
        )

        # Counter so we can rate-limit log noise — log first 3, then every
        # 25th, then the last one. Keeps the log readable while still
        # confirming the chain is alive.
        import time

        _progress_count = {
            "n": 0,
            "sent": 0,
            "failed": 0,
            "errors": {},
            "start_time": time.monotonic(),
        }
        _progress_total = len(recipients)
        # Wall-clock-based heartbeat (in addition to the per-25-event log).
        # Some campaigns are rate-limited to e.g. 30 emails/hour — at that
        # cadence the per-event log fires every 50 minutes, which an
        # operator naturally interprets as "the campaign died." A heartbeat
        # every 30s emits a "campaign N still alive, sent=X/total=Y" line
        # so the operator has unambiguous proof the engine is running even
        # during deep throttle windows.
        from time import monotonic

        _last_heartbeat = {"t": monotonic()}
        HEARTBEAT_INTERVAL = 30.0
        # DB-flush throttle: persist sent/failed counts every N events.
        # Previously the row's sent_count stayed at 0 in the DB for the
        # entire run and only jumped to its final value at completion —
        # which made the dashboard reset to 0 every time the user navigated
        # away from /campaigns and back ("running campaigns start over"),
        # and made it impossible to see how far a long campaign had
        # progressed if the browser session was lost. Persisting every
        # 25 events trades a small write amplification for accurate
        # cross-session progress reporting.
        DB_FLUSH_EVERY = 25

        def _persist_counts():
            """Flush current sent/failed counts to the DB row."""
            try:
                with app.app_context():
                    with session_scope() as session:
                        repo = CampaignRepository(session)
                        c = repo.get(campaign_id)
                        if c is None:
                            return
                        c.sent_count = _progress_count["sent"]
                        c.failed_count = _progress_count["failed"]
                        c.total_recipients = _progress_total
                        # Persist error breakdown so it survives page reloads
                        errors = _progress_count.get("errors")
                        if errors:
                            from sqlalchemy.orm.attributes import flag_modified
                            settings = dict(c.settings or {})
                            settings["error_breakdown"] = dict(errors)
                            c.settings = settings
                            flag_modified(c, "settings")
                        repo.update(c)
            except Exception as ex:
                logger.warning(
                    "Mid-run count persistence failed for campaign %s: %s "
                    "(send continues; counts will catch up at completion).",
                    campaign_id,
                    ex,
                )

        async def _progress_cb(progress: dict):
            _progress_count["n"] += 1
            n = _progress_count["n"]
            # Maintain cumulative tallies locally so we can both (a) include
            # them in the emitted payload (so the frontend SETS instead of
            # increments — eliminates the "counts don't match exactly" drift
            # caused by missed events while the tab was inactive), and
            # (b) periodically flush them to the DB so a user joining mid-
            # send (or returning after navigating away) sees real progress.
            if progress.get("success"):
                _progress_count["sent"] += 1
            else:
                _progress_count["failed"] += 1
                err_type = progress.get("error_type") or "unknown"
                _progress_count["errors"][err_type] = _progress_count["errors"].get(err_type, 0) + 1
                if progress.get("is_bounce"):
                    _progress_count["bounces"] += 1

            if n <= 3 or n % 25 == 0 or n == _progress_total:
                logger.info(
                    f"[progress] cb #{n}/{_progress_total} for campaign "
                    f"{campaign_id}: recipient={progress.get('recipient')!r} "
                    f"success={progress.get('success')}"
                )

            # Wall-clock heartbeat for rate-limited / slow campaigns where
            # the per-event log might not fire for many minutes.
            now = monotonic()
            if now - _last_heartbeat["t"] >= HEARTBEAT_INTERVAL:
                logger.info(
                    "[heartbeat] campaign %s alive — sent=%d failed=%d "
                    "total=%d (%.1f%%); thread=%s",
                    campaign_id,
                    _progress_count["sent"],
                    _progress_count["failed"],
                    _progress_total,
                    100.0
                    * (_progress_count["sent"] + _progress_count["failed"])
                    / max(_progress_total, 1),
                    threading.current_thread().name,
                )
                _last_heartbeat["t"] = now

            if n % DB_FLUSH_EVERY == 0 or n == _progress_total:
                _persist_counts()

            _emit(
                "campaign_progress",
                {
                    "campaign_id": campaign_id,
                    # Authoritative cumulative counts — frontend uses these
                    # to SET sent_count/failed_count (not increment), so the
                    # displayed value always matches what the engine has
                    # actually processed, even if some events were dropped
                    # in transit or the page just loaded.
                    "sent": _progress_count["sent"],
                    "failed": _progress_count["failed"],
                    "bounces": _progress_count["bounces"],
                    "total": _progress_total,
                    "errors": _progress_count["errors"],
                    "velocity": round(
                        (_progress_count["sent"] + _progress_count["failed"])
                        / max((monotonic() - _progress_count["start_time"]) / 60.0, 0.01),
                        1,
                    ),
                    # Per-recipient context (filtered to remove non-serializable objects
                    # and colliding keys like 'total' which is chunk-scoped)
                    **{k: v for k, v in progress.items() if k not in ("result", "total")},
                },
            )

        stats = run_async(service.run_campaign(recipients, progress_callback=_progress_cb))

        # Determine final status
        final_status = CampaignStatus.COMPLETED
        if not service._running and service._shutdown_event.is_set():
            final_status = CampaignStatus.CANCELLED

        with app.app_context():
            with session_scope() as session:

                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                if campaign is not None:
                    campaign.status = final_status
                    campaign.completed_at = datetime.now(UTC)
                    campaign.sent_count = stats.get("sent", 0)
                    campaign.failed_count = stats.get("failed", 0)
                    campaign.total_recipients = stats.get("total", len(recipients))
                    repo.update(campaign)

        _emit(
            "campaign_complete",
            {
                "campaign_id": campaign_id,
                "status": final_status.value,
                "stats": stats,
            },
        )
        logger.info(f"Campaign {campaign_id} finished: {stats}")

        # Notify webhooks of completion
        try:
            start_ts = stats.get("start_time", "")
            end_ts = stats.get("end_time", "")
            duration = 0.0
            if start_ts and end_ts:
                from datetime import datetime as _dt

                try:
                    duration = (
                        _dt.fromisoformat(end_ts) - _dt.fromisoformat(start_ts)
                    ).total_seconds()
                except Exception:
                    pass
            run_async(
                _webhook_service.notify_campaign_completed(
                    campaign_id=str(campaign_id),
                    campaign_name=config.name,
                    total=stats.get("total", 0),
                    success=stats.get("sent", 0),
                    failed=stats.get("failed", 0),
                    duration_seconds=duration,
                )
            )
        except Exception:
            pass  # Best-effort

    except Exception as exc:
        logger.exception(f"Campaign {campaign_id} crashed: {exc}")
        try:
            with app.app_context():
                with session_scope() as session:

                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    # Guard against the campaign being deleted mid-run —
                    # used to AttributeError on .status assignment, which
                    # was swallowed by the outer except below, leaving the
                    # DB stuck at status='sending' if a re-create happened.
                    if campaign is not None:
                        campaign.status = CampaignStatus.FAILED
                        campaign.completed_at = datetime.now(UTC)
                        repo.update(campaign)
        except Exception:
            logger.exception(
                "Couldn't even mark campaign %s as FAILED after a crash — "
                "the row will stay at 'sending' until manually reset.",
                campaign_id,
            )
        _emit("campaign_error", {"campaign_id": campaign_id, "error": str(exc)})
    finally:
        with _active_services_lock:
                _active_services.pop(campaign_id, None)


def register_socketio_events(sio: SocketIO):
    """Register WebSocket events."""

    from flask import current_app

    @sio.on("connect")
    def handle_connect():
        """Handle client connection.

        Requires Flask-SocketIO's ``manage_session=False`` so that
        Flask-Login's ``current_user`` proxy resolves correctly here.
        Without that, this check returns False for every connect and the
        client falls into a connect-then-disconnect loop.
        """
        if not current_user.is_authenticated:
            logger.info("SocketIO connect REJECTED: current_user not authenticated")
            return False  # Reject unauthenticated connections

        emit("connected", {"status": "connected"})
        logger.info(f"SocketIO connect OK: user={current_user.username}")

    @sio.on("disconnect")
    def handle_disconnect():
        """Handle client disconnection.

        CONTRACT: this MUST NOT touch _active_services or call .stop()
        on any campaign. Campaigns are server-side jobs that survive
        client navigation, refresh, tab close, and full browser exit.
        A disconnect just means "this browser is no longer subscribed
        to events" — the engine keeps sending.

        Logged at INFO with the active-campaign count so that
        "campaign stops on navigation" reports can be diagnosed by
        eye: a disconnect immediately followed by progress events
        ceasing for one of the listed campaigns proves the engine
        died (real bug); progress events continuing proves the
        engine is fine and the symptom is a UI staleness issue.
        """
        with _active_services_lock:
            active = list(_active_services.keys())
        logger.info(
            "SocketIO disconnect — %d campaign(s) still running on the "
            "server (%s). Disconnects do NOT stop running campaigns.",
            len(active),
            active or "[]",
        )

    @sio.on("start_campaign")
    def handle_start_campaign(data):
        """Start campaign via WebSocket.

        Emits ``campaign_started`` synchronously as an acknowledgment of the
        request — UI clients then know their start was accepted and can
        switch to a "starting…" state immediately. The actual DB load and
        recipient fetch happen on the background thread, which emits
        ``campaign_progress`` once recipients are loaded and
        ``campaign_error`` if anything fails.
        """
        # Always log the event reception so disconnected/unauthenticated
        # clicks are distinguishable from "didn't even reach the server".
        logger.info(f"start_campaign event received: data={data}")

        if not current_user.is_authenticated:
            # Emit an error rather than silently returning — otherwise the
            # client toast says "Starting…" and nothing else happens.
            emit(
                "campaign_error",
                {
                    "campaign_id": (data or {}).get("campaign_id"),
                    "error": "Not authenticated. Please reload the page and sign in.",
                },
            )
            return

        campaign_id = data.get("campaign_id")
        if not campaign_id:
            emit("campaign_error", {"error": "campaign_id required"})
            return

        with _active_services_lock:
            is_active = campaign_id in _active_services
        if is_active:
            emit(
                "campaign_error", {"campaign_id": campaign_id, "error": "Campaign already running"}
            )
            return

        # Acknowledge synchronously so the test client / UI sees the event
        # without racing the background thread's DB load.
        sio.emit(
            "campaign_started",
            {
                "campaign_id": campaign_id,
                "status": "sending",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        app = current_app._get_current_object()
        # daemon=False so the thread is NOT silently reaped when the
        # main process exits (notably: werkzeug's auto-reloader in dev
        # restarts the worker on file save, which was killing in-flight
        # campaigns out from under operators — a likely root cause for
        # "campaign stops when user navigates away" in development).
        # In production with gunicorn graceful shutdown, the worker
        # waits for non-daemon threads to finish before exiting, which
        # is the right behavior for a half-sent campaign.
        t = threading.Thread(
            target=_run_campaign_thread,
            args=(campaign_id, sio, app),
            daemon=False,
            name=f"campaign-{campaign_id}",
        )
        t.start()
        logger.info(f"Campaign {campaign_id} started via WebSocket by {current_user.username}")

    @sio.on("pause_campaign")
    def handle_pause_campaign(data):
        """Pause campaign."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get("campaign_id")
        with _active_services_lock:
            svc = _active_services.get(campaign_id)
        if svc:
            svc.pause()

            # Update DB status
            app = current_app._get_current_object()
            with app.app_context():
                with session_scope() as session:

                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    if campaign:
                        campaign.status = CampaignStatus.PAUSED
                        repo.update(campaign)

        sio.emit(
            "campaign_paused",
            {
                "campaign_id": campaign_id,
                "status": "paused",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @sio.on("resume_campaign")
    def handle_resume_campaign(data):
        """Resume campaign."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get("campaign_id")
        with _active_services_lock:
            svc = _active_services.get(campaign_id)
        if svc:
            svc.resume()

            # Update DB status back to sending
            app = current_app._get_current_object()
            with app.app_context():
                with session_scope() as session:

                    repo = CampaignRepository(session)
                    campaign = repo.get(campaign_id)
                    if campaign:
                        campaign.status = CampaignStatus.SENDING
                        repo.update(campaign)

        sio.emit(
            "campaign_resumed",
            {
                "campaign_id": campaign_id,
                "status": "sending",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @sio.on("stop_campaign")
    def handle_stop_campaign(data):
        """Stop campaign."""
        if not current_user.is_authenticated:
            return

        campaign_id = data.get("campaign_id")
        with _active_services_lock:
            svc = _active_services.get(campaign_id)
        if svc:
            svc.stop()

        # Update DB status to CANCELLED immediately so it persists across page refreshes
        app = current_app._get_current_object()
        with app.app_context():
            with session_scope() as session:
                repo = CampaignRepository(session)
                campaign = repo.get(campaign_id)
                if campaign:
                    campaign.status = CampaignStatus.CANCELLED
                    campaign.completed_at = datetime.now(UTC)
                    repo.update(campaign)

        sio.emit(
            "campaign_stopped",
            {
                "campaign_id": campaign_id,
                "status": "cancelled",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )


def emit_progress(data):
    """Emit progress update to connected clients."""
    ctx = get_app_context()
    ctx.emit_progress(data)


def emit_complete(data):
    """Emit campaign complete event."""
    ctx = get_app_context()
    ctx.emit_complete(data)
