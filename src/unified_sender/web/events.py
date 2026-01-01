"""SocketIO events."""

import logging
from datetime import datetime, UTC
from flask_socketio import SocketIO, emit
from flask_login import current_user
from ..app_context import get_app_context

logger = logging.getLogger(__name__)

def register_socketio_events(sio: SocketIO):
    """Register WebSocket events."""
    
    @sio.on('connect')
    def handle_connect():
        """Handle client connection."""
        # Note: current_user relies on Flask-Login which might require request context
        # Flask-SocketIO provides request context for connect event
        if not current_user.is_authenticated:
            return False  # Reject unauthenticated connections
        
        emit('connected', {'status': 'connected'})
        logger.info(f"Client connected via WebSocket: {current_user.username}")
    
    @sio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        logger.info("Client disconnected")
    
    @sio.on('start_campaign')
    def handle_start_campaign(data):
        """Start campaign via WebSocket."""
        if not current_user.is_authenticated:
            return
        
        campaign_id = data.get('campaign_id')
        
        # Trigger actual campaign start logic via service/task here?
        # For now, just emit status
        emit('campaign_started', {
            'campaign_id': campaign_id,
            'status': 'started',
            'timestamp': datetime.now(UTC).isoformat()
        })
        
        logger.info(f"Campaign {campaign_id} started via WebSocket by {current_user.username}")
    
    @sio.on('pause_campaign')
    def handle_pause_campaign(data):
        """Pause campaign."""
        if not current_user.is_authenticated:
            return
        
        campaign_id = data.get('campaign_id')
        
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
        
        emit('campaign_stopped', {
            'campaign_id': campaign_id,
            'status': 'stopped',
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
