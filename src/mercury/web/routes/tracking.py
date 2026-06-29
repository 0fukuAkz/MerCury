"""Tracking routes."""

from datetime import datetime, UTC
from urllib.parse import urlparse
from flask import Blueprint, request, abort, make_response, redirect
from ...services.tracking_service import TrackingService, TRACKING_PIXEL_GIF, _email_id_registry
from ...data.database import session_scope
from ...data.models import EmailLog
from ..extensions import limiter

tracking_bp = Blueprint("tracking", __name__, url_prefix="/track")


def _safe_redirect_url(url: str) -> str:
    """Return url if it uses http/https, otherwise fall back to '/'."""
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.scheme.lower() not in ("http", "https"):
            return "/"
    except Exception:
        return "/"
    return url or "/"


def _lookup_recipient(email_id: str) -> str:
    """Look up recipient email from the email_id registry, falling back to database."""
    val = _email_id_registry.get(email_id)
    if val:
        return val
    try:
        with session_scope() as session:
            log = session.query(EmailLog).filter(EmailLog.correlation_id == email_id).first()
            if log:
                # Cache it back in the registry for future fast lookups
                _email_id_registry[email_id] = log.recipient_email or ""
                return log.recipient_email or ""
    except Exception:
        pass
    return ""


def _update_email_log(email_id: str, event_type: str, ip: str = "", ua: str = ""):
    """Update EmailLog open/click counts + last-event metadata.

    Also stores the most recent IP+UA for the recipient. The campaign send
    path reads these to backfill {{location.*}} / {{ua.*}} placeholders for
    recipients whose CSV doesn't carry IP/UA columns.
    """
    try:
        with session_scope() as session:
            log = session.query(EmailLog).filter(EmailLog.correlation_id == email_id).first()
            if log:
                if event_type == "open":
                    log.open_count = (log.open_count or 0) + 1
                elif event_type == "click":
                    log.click_count = (log.click_count or 0) + 1
                # Persist the freshest IP/UA so future campaigns can
                # personalize for this recipient. UA truncated to fit the
                # column; defensive against pathological 4 KB user-agent
                # strings (real ones top out around 250 chars).
                if ip:
                    log.last_event_ip = ip[:45]
                if ua:
                    log.last_event_ua = ua[:500]
                if ip or ua:
                    log.last_event_at = datetime.now(UTC)
                session.commit()
    except Exception:
        pass  # Best-effort; don't break tracking response


@tracking_bp.route("/open/<email_id>")
@limiter.limit("60/minute")
def track_open(email_id):
    """Track email open via 1x1 transparent pixel."""
    recipient = _lookup_recipient(email_id)
    service = TrackingService(base_url=request.host_url.rstrip("/"))
    # request.user_agent.string can be empty under some werkzeug/test-client
    # combinations even when the header is set; reading the header directly
    # is the source of truth and matches what the persistence layer needs.
    _ua = request.headers.get("User-Agent", "") or (
        request.user_agent.string if request.user_agent else ""
    )
    service.record_event(
        email_id=email_id,
        event_type="open",
        recipient=recipient,
        ip_address=request.remote_addr,
        user_agent=_ua,
    )
    _update_email_log(email_id, "open", ip=request.remote_addr or "", ua=_ua)

    response = make_response(TRACKING_PIXEL_GIF)
    response.headers["Content-Type"] = "image/gif"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@tracking_bp.route("/click/<email_id>")
@limiter.limit("60/minute")
def track_click(email_id):
    """Track link click and redirect to destination."""
    url = _safe_redirect_url(request.args.get("url", "/"))
    link_id = request.args.get("lid")

    recipient = _lookup_recipient(email_id)
    service = TrackingService(base_url=request.host_url.rstrip("/"))
    _ua = request.headers.get("User-Agent", "") or (
        request.user_agent.string if request.user_agent else ""
    )
    service.record_event(
        email_id=email_id,
        event_type="click",
        recipient=recipient,
        ip_address=request.remote_addr,
        user_agent=_ua,
        metadata={"url": url, "link_id": link_id},
    )
    _update_email_log(email_id, "click", ip=request.remote_addr or "", ua=_ua)
    return redirect(url)


@tracking_bp.route("/unsubscribe/<email_id>/<token>")
@limiter.limit("10/minute")
def track_unsubscribe(email_id, token):
    """Handle unsubscribe requests."""
    from ...security.auth import validate_unsubscribe_token

    is_valid, _ = validate_unsubscribe_token(token=token, email_id=email_id)
    if not is_valid:
        abort(403, "Invalid unsubscribe token")

    recipient = _lookup_recipient(email_id)
    service = TrackingService(base_url=request.host_url.rstrip("/"))
    service.record_event(
        email_id=email_id,
        event_type="unsubscribe",
        recipient=recipient,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else "",
    )

    # In a real app, this would update recipient status too (handled by service preferably)
    # The TrackingService just records the event.
    # Service logic updates recipient.

    return "You have been unsubscribed successfully.", 200
