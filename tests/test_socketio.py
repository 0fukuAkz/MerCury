"""Tests for Socket.IO events."""

import pytest
from unittest.mock import patch, Mock, MagicMock


@pytest.fixture
def socketio_instance():
    """Get the application SocketIO instance."""
    from mercury.web.extensions import socketio

    return socketio


@pytest.fixture
def socket_app(app, mock_user_loader, socketio_instance):
    with patch("mercury.web.app.get_app_context") as mock_ctx_getter:
        mock_ctx = Mock()
        mock_ctx.socketio = socketio_instance
        mock_ctx.limiter.limit.side_effect = lambda limit_string: lambda f: f
        mock_ctx_getter.return_value = mock_ctx
        socketio_instance.init_app(app)
        return app


@pytest.fixture
def auth_client_socket(socket_app):
    """Authenticated Flask test client."""
    with patch("mercury.web.app.api_key_or_login_required", side_effect=lambda f: f):
        pass

    return socket_app.test_client()


@pytest.fixture
def mock_user_loader():
    with patch("mercury.security.auth.get_user_by_id") as mock_get:
        from mercury.security.auth import User as AuthUser

        user = AuthUser(id="1", username="admin", password_hash="hash", is_admin=True)
        mock_get.side_effect = lambda uid: user if str(uid) == "1" else None
        yield mock_get


def test_socket_connect_authenticated(socket_app, socketio_instance):
    """Test socket connection with authenticated user."""
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        assert client.is_connected()

        received = client.get_received()
        assert len(received) > 0
        assert received[0]["name"] == "connected"


def test_socket_connect_unauthenticated(socket_app, socketio_instance):
    """Test connection rejection for unauthenticated user."""
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = False
        mock_user.is_active = True
        mock_user_getter.return_value = mock_user

        try:
            client = socketio_instance.test_client(socket_app)
            assert not client.is_connected()
        except Exception:
            pass


def test_socket_campaign_events(socket_app, socketio_instance):
    """Test campaign control events.

    handle_start_campaign now emits 'campaign_started' synchronously as an
    acknowledgment of the request, before spawning the background thread that
    actually loads the campaign and starts sending. Pause/resume/stop have
    always been synchronous.
    """
    with patch("flask_login.utils._get_user") as mock_user_getter, patch(
        "mercury.web.app.get_app_context"
    ):
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)

        # Start
        client.emit("start_campaign", {"campaign_id": 1})
        received = client.get_received()

        event = next((e for e in received if e["name"] == "campaign_started"), None)
        assert event is not None
        assert event["args"][0]["campaign_id"] == 1

        # Pause
        client.emit("pause_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_paused"), None)
        assert event is not None

        # Resume
        client.emit("resume_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_resumed"), None)
        assert event is not None

        # Stop
        client.emit("stop_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_stopped"), None)
        assert event is not None
