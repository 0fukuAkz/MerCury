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
    # Consciously accept the in-memory limiter and SQLite so the preflight
    # downgrades them from hard errors to warnings (the path under test).
    monkeypatch.setenv("ALLOW_INMEMORY_RATE_LIMIT", "1")
    monkeypatch.setenv("ALLOW_SQLITE_IN_PRODUCTION", "1")

    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch("mercury.web.app.configure_logging"), patch("mercury.web.app.logger") as mock_logger:
        # Mock session to bypass database setup/migrations
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            app = create_app()
            assert app.config["ENV"] == "production"

            # Check warning log calls
            warning_messages = [call[0][1] for call in mock_logger.warning.call_args_list]
            assert any("API_KEYS not set" in msg for msg in warning_messages)
            assert any("RATE_LIMIT_STORAGE is in-memory" in msg for msg in warning_messages)


def test_app_factory_prod_rejects_sqlite_and_inmemory_ratelimit(monkeypatch):
    """Without the conscious escape hatches, SQLite + in-memory rate limiting
    are hard preflight failures in production, reported together."""
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prodsecret")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", "memory://")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALLOW_SQLITE_IN_PRODUCTION", raising=False)
    monkeypatch.delenv("ALLOW_INMEMORY_RATE_LIMIT", raising=False)

    # Preflight raises before any DB/auth init, so no patching is needed.
    with pytest.raises(RuntimeError) as exc:
        create_app()
    msg = str(exc.value)
    assert "Production preflight failed" in msg
    assert "SQLite" in msg
    assert "in-memory" in msg


def test_app_factory_prod_accepts_postgres_and_redis(monkeypatch):
    """The happy production path: a networked DB + redis limiter clears
    preflight (no hard error) without any escape hatch."""
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prodsecret")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass")
    monkeypatch.setenv("API_KEYS", "live-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/mercury")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", "redis://localhost:6379")

    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch("mercury.web.app.configure_logging"):
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            app = create_app()
            assert app.config["ENV"] == "production"


def test_prod_multiworker_allowed_when_prereqs_met(monkeypatch):
    """WEB_CONCURRENCY>1 is allowed (no multi-worker warning) once event fan-out
    + redis rate-limit + worker execution are all configured."""
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prodsecret")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/mercury")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", "redis://localhost:6379")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("SOCKETIO_MESSAGE_QUEUE", "redis://localhost:6379/1")
    monkeypatch.setenv("CAMPAIGN_EXECUTION_MODE", "worker")

    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch("mercury.web.app.configure_logging"), patch("mercury.web.app.logger") as mock_logger:
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            create_app()
            warnings = [c[0][1] for c in mock_logger.warning.call_args_list]
            assert not any("multi-worker-safe" in m for m in warnings)


def test_prod_multiworker_warns_when_prereqs_missing(monkeypatch):
    """WEB_CONCURRENCY>1 without the shared-state prerequisites warns, naming
    exactly what's missing."""
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prodsecret")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/mercury")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", "redis://localhost:6379")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.delenv("SOCKETIO_MESSAGE_QUEUE", raising=False)
    monkeypatch.delenv("CAMPAIGN_EXECUTION_MODE", raising=False)

    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch("mercury.web.app.configure_logging"), patch("mercury.web.app.logger") as mock_logger:
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            create_app()
            warnings = [c[0][1] for c in mock_logger.warning.call_args_list]
            assert any("not multi-worker-safe" in m for m in warnings)
            assert any("SOCKETIO_MESSAGE_QUEUE" in m for m in warnings)
            assert any("CAMPAIGN_EXECUTION_MODE=worker" in m for m in warnings)


def test_app_load_user_exception():
    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ):
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

    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch("alembic.command.upgrade", side_effect=Exception("Alembic connection issue")), patch(
        "mercury.web.app.logger"
    ) as mock_logger:
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            create_app()
            # Verify exception warning was logged
            warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
            assert any("Alembic migration failed" in call for call in warning_calls)


def test_stale_campaign_reconciliation_raises_exception():
    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch(
        "mercury.data.database.get_session_direct", side_effect=Exception("Database down")
    ), patch("mercury.web.app.logger") as mock_logger:
        create_app()
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        assert any("Stale-campaign reconciliation skipped" in call for call in warning_calls)


def test_websocket_patch_shutdown_exception():
    import importlib.util

    if importlib.util.find_spec("eventlet") is None:
        pytest.skip("eventlet not installed")

    mock_socket = MagicMock()
    mock_socket.shutdown.side_effect = OSError(9, "Bad file descriptor")  # EBADF

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
    with patch("mercury.web.app.init_db"), patch("mercury.web.app.init_auth"), patch(
        "mercury.web.app.start_background_loop"
    ), patch("mercury.web.extensions.socketio.run") as mock_run:
        mock_session = MagicMock()
        with patch("mercury.data.database.get_session_direct", return_value=mock_session):
            runpy.run_module("mercury.web.app", run_name="__main__")
            mock_run.assert_called_once()
