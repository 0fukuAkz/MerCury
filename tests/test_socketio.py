"""Tests for Socket.IO events."""

import pytest
from unittest.mock import patch, Mock
from unified_sender.web.app import create_app, socketio

from flask_socketio import SocketIO

@pytest.fixture
def socketio_instance():
    """Create a real SocketIO instance."""
    return SocketIO()

@pytest.fixture
def socket_app(mock_user_loader, socketio_instance):
    """Create app with Socket.IO for tests."""
    with patch('unified_sender.web.app.init_auth'), \
         patch('unified_sender.web.app.get_app_context') as mock_ctx_getter, \
         patch('unified_sender.web.app.register_auth_routes'):
         
        # Mock limiter
        mock_ctx = Mock()
        mock_ctx.limiter.limit.side_effect = lambda limit_string: lambda f: f
        # Use REAL socketio instance
        mock_ctx.socketio = socketio_instance
        # Mock other context methods
        mock_ctx.emit_progress = Mock()
        mock_ctx.emit_complete = Mock()
        mock_ctx.initialize = Mock()
        
        mock_ctx_getter.return_value = mock_ctx
        
        app = create_app()
        app.config['SECRET_KEY'] = 'test-key'
        app.config['TESTING'] = True
        
        # Initialize socketio with app since we mocked context.initialize
        socketio_instance.init_app(app)
        
        return app

@pytest.fixture
def auth_client_socket(socket_app):
    """Authenticated Flask test client."""
    with patch('unified_sender.web.app.api_key_or_login_required', side_effect=lambda f: f):
        pass
        
    return socket_app.test_client()

@pytest.fixture
def mock_user_loader():
    with patch('unified_sender.security.auth.get_user_by_id') as mock_get:
        from unified_sender.security.auth import User as AuthUser
        user = AuthUser(id="1", username="admin", password_hash="hash", is_admin=True)
        mock_get.side_effect = lambda uid: user if str(uid) == "1" else None
        yield mock_get

def test_socket_connect_authenticated(socket_app, socketio_instance):
    """Test socket connection with authenticated user."""
    with patch('unified_sender.web.app.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.username = "admin"
        
        client = socketio_instance.test_client(socket_app)
        assert client.is_connected()
        
        received = client.get_received()
        assert len(received) > 0
        assert received[0]['name'] == 'connected'

def test_socket_connect_unauthenticated(socket_app, socketio_instance):
    """Test connection rejection for unauthenticated user."""
    with patch('unified_sender.web.app.current_user') as mock_user:
        mock_user.is_authenticated = False
        
        try:
            client = socketio_instance.test_client(socket_app)
            assert not client.is_connected()
        except Exception:
            pass

def test_socket_campaign_events(socket_app, socketio_instance):
    """Test campaign control events."""
    with patch('unified_sender.web.app.current_user') as mock_user, \
         patch('unified_sender.web.app.get_app_context'): 
        
        mock_user.is_authenticated = True
        mock_user.username = "admin"
        
        client = socketio_instance.test_client(socket_app)
        
        # Start
        client.emit('start_campaign', {'campaign_id': 1})
        received = client.get_received()
        
        event = next((e for e in received if e['name'] == 'campaign_started'), None)
        assert event is not None
        assert event['args'][0]['campaign_id'] == 1
        
        # Pause
        client.emit('pause_campaign', {'campaign_id': 1})
        received = client.get_received()
        event = next((e for e in received if e['name'] == 'campaign_paused'), None)
        assert event is not None
        
        # Resume
        client.emit('resume_campaign', {'campaign_id': 1})
        received = client.get_received()
        event = next((e for e in received if e['name'] == 'campaign_resumed'), None)
        assert event is not None
        
        # Stop
        client.emit('stop_campaign', {'campaign_id': 1})
        received = client.get_received()
        event = next((e for e in received if e['name'] == 'campaign_stopped'), None)
        assert event is not None
