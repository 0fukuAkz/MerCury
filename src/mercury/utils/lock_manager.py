"""Distributed or local lock manager to serialize concurrent operations."""

import os
import logging
import time
import threading

logger = logging.getLogger(__name__)


class LockManager:
    """Distributed or local lock manager.

    Tries Redis first (if configured), falls back to file locking via fcntl,
    and finally falls back to threading.Lock.
    """

    _mem_locks = {}
    _mem_locks_lock = threading.Lock()

    def __init__(self, name: str, timeout: float = 300):
        self.name = name
        self.timeout = timeout
        self._redis_client = None
        self._lock = None
        self._file_handle = None

        redis_url = os.environ.get("REDIS_URL") or os.environ.get("RATE_LIMIT_STORAGE")
        if redis_url and redis_url.startswith("redis"):
            try:
                import redis  # type: ignore

                self._redis_client = redis.Redis.from_url(redis_url)
            except ImportError:
                logger.debug("redis library not installed; falling back to file locking")
            except Exception as e:
                logger.debug("Failed to connect to Redis for lock %s: %s; falling back to file locking", name, e)

    def acquire(self, blocking: bool = True) -> bool:
        """Acquire the lock."""
        if self._redis_client:
            try:
                lock_key = f"lock:{self.name}"
                identifier = str(time.time())

                start_time = time.time()
                while True:
                    if self._redis_client.set(lock_key, identifier, ex=int(self.timeout), nx=True):
                        self._lock = identifier
                        return True
                    if not blocking or (time.time() - start_time) > self.timeout:
                        return False
                    time.sleep(0.1)
            except Exception as e:
                logger.warning("Redis lock acquisition failed for %s: %s; falling back to file locking", self.name, e)
                self._redis_client = None

        # Fallback 1: File locking (Unix-only fcntl)
        try:
            import fcntl
            from .app_dirs import get_log_dir

            lock_dir = get_log_dir()
            os.makedirs(lock_dir, exist_ok=True)
            lock_path = os.path.join(lock_dir, f"{self.name}.lock")

            self._file_handle = open(lock_path, "w")
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB

            fcntl.flock(self._file_handle.fileno(), flags)
            return True
        except (ImportError, OSError, IOError) as e:
            logger.debug("File locking not supported or failed: %s; falling back to threading.Lock", e)

        # Fallback 2: Threading Lock
        return self._acquire_memory_lock(blocking)

    def _acquire_memory_lock(self, blocking: bool) -> bool:
        with LockManager._mem_locks_lock:
            if self.name not in LockManager._mem_locks:
                LockManager._mem_locks[self.name] = threading.Lock()
            lock = LockManager._mem_locks[self.name]

        if blocking:
            acquired = lock.acquire(blocking=True, timeout=self.timeout)
        else:
            acquired = lock.acquire(blocking=False)
        if acquired:
            self._lock = lock
        return acquired

    def release(self) -> None:
        """Release the lock."""
        if self._redis_client and self._lock:
            try:
                lock_key = f"lock:{self.name}"
                val = self._redis_client.get(lock_key)
                if val and val.decode("utf-8") == self._lock:
                    self._redis_client.delete(lock_key)
            except Exception as e:
                logger.warning("Failed to release Redis lock %s: %s", self.name, e)
            finally:
                self._lock = None

        if self._file_handle:
            try:
                import fcntl

                fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
                self._file_handle.close()
            except Exception:
                pass
            finally:
                self._file_handle = None

        if self._lock and hasattr(self._lock, "release"):
            try:
                self._lock.release()
            except Exception:
                pass
            finally:
                self._lock = None

    def __enter__(self):
        acquired = self.acquire(blocking=True)
        if not acquired:
            raise RuntimeError(f"Could not acquire lock: {self.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
