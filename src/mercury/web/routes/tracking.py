"""Tracking routes."""

from flask import Blueprint, request, abort, make_response
from ...services.tracking_service import TrackingService, TRACKING_PIXEL_GIF

tracking_bp = Blueprint('tracking', __name__, url_prefix='/track')

@tracking_bp.route('/open/<email_id>')
def track_open(email_id):
    """Track email open via 1x1 transparent pixel."""
    service = TrackingService()
    service.record_event(
        email_id=email_id,
        event_type='open',
        recipient='',  # Would be looked up from email_id via service logic if expanded
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else ''
    )
    
    response = make_response(TRACKING_PIXEL_GIF)
    response.headers['Content-Type'] = 'image/gif'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@tracking_bp.route('/click/<email_id>')
def track_click(email_id):
    """Track link click and redirect to destination."""
    url = request.args.get('url', '/')
    link_id = request.args.get('lid')
    
    service = TrackingService()
    service.record_event(
        email_id=email_id,
        event_type='click',
        recipient='',
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else '',
        extra_data={'url': url, 'link_id': link_id}
    )
    
    from flask import redirect
    return redirect(url)

@tracking_bp.route('/unsubscribe/<email_id>/<token>')
def track_unsubscribe(email_id, token):
    """Handle unsubscribe requests."""
    from ...security.auth import validate_unsubscribe_token
    
    if not validate_unsubscribe_token(email_id, token):
        abort(403, 'Invalid unsubscribe token')
    
    service = TrackingService()
    service.record_event(
        email_id=email_id,
        event_type='unsubscribe',
        recipient='',
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string if request.user_agent else ''
    )
    
    # In a real app, this would update recipient status too (handled by service preferably)
    # The TrackingService just records the event.
    # Service logic updates recipient.
    
    return "You have been unsubscribed successfully.", 200
