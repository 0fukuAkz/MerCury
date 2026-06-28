"""Tests for LockManager."""

import os
import sys
from unittest.mock import patch, MagicMock

# Create a fake redis module to allow patching when redis is not installed
fake_redis = MagicMock()
sys.modules["redis"] = fake_redis

from mercury.utils.lock_manager import LockManager  # noqa: E402  (after fake-redis registration)


def test_lock_manager_redis_import_error():
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}):
        with patch.dict("sys.modules", {"redis": None}):
            # Should gracefully fall back if redis is not installed
            lock = LockManager("test_no_redis")
            assert lock._redis_client is None


def test_lock_manager_redis_connection_error():
    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", side_effect=Exception("Conn error")
    ):
        lock = LockManager("test_conn_error")
        assert lock._redis_client is None


def test_lock_manager_redis_lock_timeout():
    mock_redis = MagicMock()
    mock_redis.set.return_value = False  # Never acquire the lock

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", return_value=mock_redis
    ):
        lock = LockManager("test_timeout", timeout=0.1)

        # blocking=True but will hit the timeout branch
        acquired = lock.acquire(blocking=True)
        assert acquired is False


def test_lock_manager_redis_acquire_exception():
    mock_redis = MagicMock()
    mock_redis.set.side_effect = Exception("Redis went down")

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", return_value=mock_redis
    ), patch("mercury.utils.lock_manager.LockManager._acquire_memory_lock", return_value=True):
        lock = LockManager("test_acq_ex")
        acquired = lock.acquire()
        assert acquired is True
        assert lock._redis_client is None  # Should have been cleared on error


def test_lock_manager_redis_release_exception():
    """A failure inside the atomic release is swallowed and still clears _lock."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    # Release now runs a server-side Lua compare-and-delete via eval().
    mock_redis.eval.side_effect = Exception("Eval failed")

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", return_value=mock_redis
    ):
        lock = LockManager("test_rel_ex")
        lock.acquire()
        assert lock._lock is not None

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


# --- Concurrency soundness: Redis fencing token + atomic release ----------


def test_redis_token_is_unique_not_clock_derived():
    """Tokens must be unique per acquisition, independent of the clock.

    Two acquisitions pinned to the *same* wall-clock instant must still get
    distinct tokens; otherwise two holders could delete each other's lock.
    """
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", return_value=mock_redis
    ), patch("mercury.utils.lock_manager.time.time", return_value=123.0):
        lock_a = LockManager("job_dup")
        lock_a.acquire()
        token_a = lock_a._lock

        lock_b = LockManager("job_dup")
        lock_b.acquire()
        token_b = lock_b._lock

    assert token_a and token_b
    assert token_a != token_b  # distinct despite identical frozen clock


def test_redis_acquire_sets_nx_with_token_and_ttl():
    """acquire() must use SET NX with an expiry so a dead holder self-heals."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", return_value=mock_redis
    ):
        lock = LockManager("job_nx", timeout=300)
        assert lock.acquire() is True

    args, kwargs = mock_redis.set.call_args
    assert args[0] == "lock:job_nx"
    assert args[1] == lock._lock  # the token we now hold
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == 300


def test_redis_release_is_atomic_compare_and_delete():
    """release() must compare-and-delete via a single eval(), not get+delete."""
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}), patch(
        "redis.Redis.from_url", return_value=mock_redis
    ):
        lock = LockManager("job_atomic")
        lock.acquire()
        held_token = lock._lock

        lock.release()

    # The old, racy GET-then-DELETE path must be gone.
    mock_redis.get.assert_not_called()
    mock_redis.delete.assert_not_called()

    # Exactly one atomic compare-and-delete, keyed on our own token.
    mock_redis.eval.assert_called_once()
    eval_args = mock_redis.eval.call_args.args
    assert eval_args[1] == 1  # numkeys
    assert eval_args[2] == "lock:job_atomic"  # KEYS[1]
    assert eval_args[3] == held_token  # ARGV[1] == our token
    assert lock._lock is None
