"""Tests targeting full coverage of the LockManager utility class."""

import sys
import os
from unittest.mock import MagicMock, patch
import pytest
from mercury.utils.lock_manager import LockManager

def test_lock_manager_redis_success():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.get.return_value = b"123"
    
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), \
         patch.dict(sys.modules, {"redis": MagicMock(Redis=MagicMock(from_url=MagicMock(return_value=mock_redis)))}):
        lock = LockManager("test_redis_success", timeout=5)
        assert lock.acquire(blocking=False) is True
        assert lock._lock is not None
        
        # Release
        # Set mock_redis.get return to decode properly to identity
        lock._lock = "123"
        lock.release()
        mock_redis.delete.assert_called_with("lock:test_redis_success")

def test_lock_manager_redis_failure_and_file_fallback():
    mock_redis = MagicMock()
    mock_redis.set.return_value = False
    
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), \
         patch.dict(sys.modules, {"redis": MagicMock(Redis=MagicMock(from_url=MagicMock(return_value=mock_redis)))}):
        lock = LockManager("test_redis_fail_fallback", timeout=1)
        # Test redis exception to trigger fallback
        mock_redis.set.side_effect = Exception("Redis connection refused")
        
        with patch("fcntl.flock") as mock_flock, \
             patch("builtins.open", create=True) as mock_open:
            assert lock.acquire(blocking=False) is True
            mock_flock.assert_called_once()
            
            # release
            lock.release()
            mock_flock.assert_called_with(mock_open.return_value.fileno(), 8) # LOCK_UN = 8

def test_lock_manager_file_lock_failure_and_thread_fallback():
    # redis is not configured
    with patch.dict(os.environ, {}), patch("os.environ.get", return_value=None):
        lock = LockManager("test_thread_fallback", timeout=2)
        # Force fcntl flock to fail/import error
        with patch.dict(sys.modules, {"fcntl": None}):
            # Should fallback to threading.Lock
            # Let's acquire in thread 1
            assert lock.acquire(blocking=True) is True
            
            # Now try to acquire in thread 2 (should fail or timeout)
            # Create a second LockManager with same name
            lock2 = LockManager("test_thread_fallback", timeout=0.1)
            assert lock2.acquire(blocking=False) is False
            
            lock.release()
            assert lock2.acquire(blocking=False) is True
            lock2.release()

def test_lock_manager_context_manager():
    with patch.dict(os.environ, {}), patch.dict(sys.modules, {"fcntl": None}):
        with LockManager("test_context", timeout=1) as lock:
            assert lock._lock is not None
        # should be released automatically
        assert lock._lock is None

def test_lock_manager_context_manager_fail():
    with patch.dict(os.environ, {}), patch.dict(sys.modules, {"fcntl": None}):
        lock1 = LockManager("test_context_fail", timeout=0.1)
        assert lock1.acquire() is True
        
        lock2 = LockManager("test_context_fail", timeout=0.1)
        with pytest.raises(RuntimeError):
            with lock2:
                pass
        
        lock1.release()
