"""Tests for LockManager."""

import os
import threading
import time
import pytest
import sys
from unittest.mock import patch, MagicMock

# Create a fake redis module to allow patching when redis is not installed
fake_redis = MagicMock()
sys.modules["redis"] = fake_redis

from mercury.utils.lock_manager import LockManager


def test_lock_manager_redis_import_error():
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}):
        with patch.dict("sys.modules", {"redis": None}):
            # Should gracefully fall back if redis is not installed
            lock = LockManager("test_no_redis")
            assert lock._redis_client is None


def test_lock_manager_redis_connection_error():
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), \
         patch("redis.Redis.from_url", side_effect=Exception("Conn error")):
        lock = LockManager("test_conn_error")
        assert lock._redis_client is None


def test_lock_manager_redis_lock_timeout():
    mock_redis = MagicMock()
    mock_redis.set.return_value = False  # Never acquire the lock
    
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), \
         patch("redis.Redis.from_url", return_value=mock_redis):
        lock = LockManager("test_timeout", timeout=0.1)
        
        # blocking=True but will hit the timeout branch
        acquired = lock.acquire(blocking=True)
        assert acquired is False


def test_lock_manager_redis_acquire_exception():
    mock_redis = MagicMock()
    mock_redis.set.side_effect = Exception("Redis went down")
    
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), \
         patch("redis.Redis.from_url", return_value=mock_redis), \
         patch("mercury.utils.lock_manager.LockManager._acquire_memory_lock", return_value=True):
        
        lock = LockManager("test_acq_ex")
        acquired = lock.acquire()
        assert acquired is True
        assert lock._redis_client is None  # Should have been cleared on error


def test_lock_manager_redis_release_exception():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.get.return_value = b"test_id"
    mock_redis.delete.side_effect = Exception("Delete failed")
    
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), \
         patch("redis.Redis.from_url", return_value=mock_redis), \
         patch("time.time", return_value=123.0):
         
        lock = LockManager("test_rel_ex")
        lock.acquire()
        lock._lock = "123.0"  # Match the fake time
        
        # Should catch exception and clear _lock
        lock.release()
        assert lock._lock is None


def test_lock_manager_file_release_exception():
    lock = LockManager("test_file_rel")
    mock_file = MagicMock()
    lock._file_handle = mock_file
    
    with patch("fcntl.flock", side_effect=Exception("fcntl error")):
        lock.release()
        assert lock._file_handle is None


def test_lock_manager_thread_release_exception():
    lock = LockManager("test_thread_rel")
    mock_thread_lock = MagicMock()
    mock_thread_lock.release.side_effect = Exception("thread error")
    lock._lock = mock_thread_lock
    
    lock.release()
    assert lock._lock is None
