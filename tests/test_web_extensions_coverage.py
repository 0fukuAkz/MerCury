"""Tests targeting full coverage of web/extensions.py."""

import queue
import importlib
from unittest.mock import MagicMock, patch
import pytest

import mercury.web.extensions

def test_queue_emit_full():
    with patch("mercury.web.extensions._emit_queue.put_nowait", side_effect=queue.Full), \
         patch("mercury.web.extensions.logger") as mock_logger:
        mercury.web.extensions.queue_emit("test_event", {"data": 123})
        mock_logger.warning.assert_called_once_with("emit bridge queue full; dropped event %r", "test_event")

def test_drain_emit_queue_exception():
    mock_sio = MagicMock()
    mock_sio.emit.side_effect = Exception("Emit failed")
    
    # Put one event in the queue
    mercury.web.extensions._emit_queue.put(("error_event", {"val": 1}))
    
    class StopLoop(Exception):
        pass
        
    # Mock queue.get to raise StopLoop on second call to terminate loop
    call_count = 0
    original_get = mercury.web.extensions._emit_queue.get
    def mock_get(timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise StopLoop()
        return original_get(timeout=timeout)
        
    with patch.object(mercury.web.extensions._emit_queue, "get", side_effect=mock_get), \
         patch("mercury.web.extensions.logger") as mock_logger:
        with pytest.raises(StopLoop):
            mercury.web.extensions._drain_emit_queue(mock_sio)
        
    # Check warning was logged
    mock_logger.warning.assert_called_once()
    assert "emit bridge: failed to emit" in mock_logger.warning.call_args[0][0]

def test_start_emit_bridge_idempotent():
    mock_sio = MagicMock()
    mock_sio._mercury_bridge_started = True
    
    mercury.web.extensions.start_emit_bridge(mock_sio)
    mock_sio.start_background_task.assert_not_called()

def test_cors_config_parsing(monkeypatch):
    # Test "*"
    monkeypatch.setenv("CORS_ORIGINS", "*")
    importlib.reload(mercury.web.extensions)
    assert mercury.web.extensions._cors_origins == "*"
    
    # Test specific list
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://example.com")
    importlib.reload(mercury.web.extensions)
    assert mercury.web.extensions._cors_origins == ["http://localhost:3000", "https://example.com"]
    
    # Test empty
    monkeypatch.setenv("CORS_ORIGINS", "")
    importlib.reload(mercury.web.extensions)
    assert mercury.web.extensions._cors_origins == []
    
    # Restore defaults
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    importlib.reload(mercury.web.extensions)

@pytest.mark.asyncio
async def test_periodic_smtp_health_check_success():
    # Setup mocks for database and service
    mock_session = MagicMock()
    mock_repo = MagicMock()
    mock_server = MagicMock()
    mock_server.is_enabled = True
    mock_server.get_connection_config.return_value = {"host": "smtp.test.com"}
    mock_repo.get_all.return_value = [mock_server]
    
    from unittest.mock import AsyncMock
    with patch("mercury.web.extensions.asyncio.sleep") as mock_sleep, \
         patch("mercury.services.smtp_service.SMTPService") as MockService, \
         patch("mercury.data.database.session_scope") as mock_scope, \
         patch("mercury.data.repositories.smtp.SMTPRepository", return_value=mock_repo):
         
        mock_scope.return_value.__enter__.return_value = mock_session
        MockService.return_value.check_all_health = AsyncMock()
        
        # We raise a custom exception inside sleep to break the infinite loop
        class StopLoopException(Exception):
            pass
        # First sleep is 30, second is 300
        mock_sleep.side_effect = [None, StopLoopException("stop")]
        
        with pytest.raises(StopLoopException):
            await mercury.web.extensions._periodic_smtp_health_check()
            
        MockService.return_value.check_all_health.assert_called_once()

@pytest.mark.asyncio
async def test_periodic_smtp_health_check_exception():
    with patch("mercury.web.extensions.asyncio.sleep") as mock_sleep, \
         patch("mercury.data.database.session_scope", side_effect=Exception("DB Down")), \
         patch("mercury.web.extensions.logger") as mock_logger:
         
        class StopLoopException(Exception):
            pass
        mock_sleep.side_effect = [None, StopLoopException("stop")]
        
        with pytest.raises(StopLoopException):
            await mercury.web.extensions._periodic_smtp_health_check()
            
        mock_logger.exception.assert_called_once_with("Error in background SMTP health check daemon")

def test_start_background_loop_running():
    # Test early return when loop is already running
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    
    with patch("mercury.web.extensions._background_loop", mock_loop):
        loop = mercury.web.extensions.start_background_loop()
        assert loop is mock_loop
