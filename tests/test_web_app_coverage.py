"""Tests for web/app.py factory boot, production check paths, exceptions, and security headers."""

import runpy
from unittest.mock import MagicMock, patch
import pytest
from mercury.web.app import create_app

def test_app_factory_prod_no_secret_key(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
        create_app()

def test_app_factory_prod_no_admin_password(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prodsecret")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD is not set"):
        create_app()

def test_app_factory_prod_preflight_warnings(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prodsecret")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass")
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", "memory://")
    
    with patch("mercury.web.app.init_db"), \
         patch("mercury.web.app.init_auth"), \
         patch("mercury.web.app.start_background_loop"), \
         patch("mercury.web.app.configure_logging"), \
         patch("mercury.web.app.logger") as mock_logger:
        # Mock session to bypass database setup/migrations
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            app = create_app()
            assert app.config["ENV"] == "production"
            
            # Check warning log calls
            warning_messages = [call[0][1] for call in mock_logger.warning.call_args_list]
            assert any("API_KEYS not set" in msg for msg in warning_messages)
            assert any("RATE_LIMIT_STORAGE is in-memory" in msg for msg in warning_messages)

def test_app_load_user_exception():
    with patch("mercury.web.app.init_db"), \
         patch("mercury.web.app.init_auth"), \
         patch("mercury.web.app.start_background_loop"):
         mock_session = MagicMock()
         with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            app = create_app(config={"TESTING": True})
            # Find the user_loader registered function
            login_manager = getattr(app, "login_manager", None)
            assert login_manager is not None
            
            # Mock get_user_by_id to raise Exception
            with patch("mercury.web.app.get_user_by_id", side_effect=ValueError("Invalid User")):
                user = login_manager._user_callback("123")
                assert user is None

def test_alembic_upgrade_failed_logged(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    
    with patch("mercury.web.app.init_db"), \
         patch("mercury.web.app.init_auth"), \
         patch("mercury.web.app.start_background_loop"), \
         patch("alembic.command.upgrade", side_effect=Exception("Alembic connection issue")), \
         patch("mercury.web.app.logger") as mock_logger:
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            create_app()
            # Verify exception warning was logged
            warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
            assert any("Alembic migration failed" in call for call in warning_calls)

def test_stale_campaign_reconciliation_raises_exception():
    with patch("mercury.web.app.init_db"), \
         patch("mercury.web.app.init_auth"), \
         patch("mercury.web.app.start_background_loop"), \
         patch("mercury.data.database.get_session_direct", side_effect=Exception("Database down")), \
         patch("mercury.web.app.logger") as mock_logger:
        create_app()
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        assert any("Stale-campaign reconciliation skipped" in call for call in warning_calls)

def test_websocket_patch_shutdown_exception():
    import importlib.util
    if importlib.util.find_spec("eventlet") is None:
        pytest.skip("eventlet not installed")
        
    mock_socket = MagicMock()
    mock_socket.shutdown.side_effect = OSError(9, "Bad file descriptor") # EBADF
    
    class FakeWebSocket:
        def __init__(self):
            self.socket = mock_socket
            self.log = MagicMock()
            self.log_context = "test"
            
        def _send_closing_frame(self, *args, **kwargs):
            pass
            
    # Test safe shutdown via monkey-patched close logic
    from mercury.web.app import _safe_shutdown
    ws = FakeWebSocket()
    _safe_shutdown(ws, ws._send_closing_frame, True)
    
    # Verify socket close was still called in finally block
    mock_socket.close.assert_called_once()
    
    # Test other OSError types (e.g. unknown errno)
    mock_socket.shutdown.side_effect = OSError(99, "Unknown error")
    ws = FakeWebSocket()
    _safe_shutdown(ws, ws._send_closing_frame, True)
    ws.log.write.assert_called_once()

def test_main_block():
    with patch("mercury.web.app.init_db"), \
         patch("mercury.web.app.init_auth"), \
         patch("mercury.web.app.start_background_loop"), \
         patch("mercury.web.extensions.socketio.run") as mock_run:
        
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            runpy.run_module("mercury.web.app", run_name="__main__")
            mock_run.assert_called_once()
