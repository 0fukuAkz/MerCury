"""Database configuration and session management."""

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Generator, Iterator, Optional
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

Base = declarative_base()

logger = logging.getLogger(__name__)

_engine = None
_engine_url = None
_SessionLocal = None
_engine_lock = threading.Lock()
_session_lock = threading.Lock()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in dbapi_connection.__class__.__module__.lower():
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine(db_url: Optional[str] = None):
    """Get or create database engine.

    Only the first call in a process actually creates the engine; later
    calls return the cached one. If a later call passes a different
    ``db_url`` than what's already cached, that argument is silently
    ignored — log a warning so the mismatch is at least visible instead of
    failing in surprising ways (e.g. CLI and web app racing to init_db()
    with different DATABASE_URLs in the same process).
    """
    global _engine, _engine_url

    if _engine is None:
        with _engine_lock:
            if _engine is None:
                if db_url is None:
                    # Use app_dirs to determine correct path (local or system user data)
                    from mercury.utils.app_dirs import get_db_path

                    db_path = get_db_path()
                else:
                    db_path = db_url

                is_sqlite = "sqlite" in db_path
                engine_kwargs: dict[str, Any] = {
                    "echo": os.environ.get("SQL_DEBUG", "").lower() == "true",
                    # Verify a pooled connection is still alive before handing it
                    # out (cheap "SELECT 1"). Harmless for SQLite; essential for
                    # networked engines (Postgres/MySQL) whose connections die on
                    # server restart, idle timeout, or a proxy (PgBouncer) culling
                    # the socket — without it the first query after such an event
                    # raises instead of transparently reconnecting.
                    "pool_pre_ping": True,
                }
                if is_sqlite:
                    # MerCury's web worker, background asyncio loop, and health
                    # checks all touch the engine from different threads.
                    engine_kwargs["connect_args"] = {"check_same_thread": False}
                else:
                    # Recycle connections older than 30 min so we stay under
                    # common server-side idle cutoffs (MySQL wait_timeout,
                    # managed-Postgres / PgBouncer idle limits) rather than
                    # handing out a soon-to-be-dropped socket.
                    engine_kwargs["pool_recycle"] = 1800
                _engine = create_engine(db_path, **engine_kwargs)
                _engine_url = db_path
    elif db_url is not None and db_url != _engine_url:
        logger.warning(
            "get_engine() called with db_url=%r but the engine is already "
            "initialized with %r; the requested URL is ignored. Call "
            "init_db() once, before any other db access, with the URL you "
            "intend to use for the lifetime of the process.",
            db_url,
            _engine_url,
        )

    return _engine


def get_session() -> Generator[Session, None, None]:
    """Get database session as context manager."""
    global _SessionLocal

    if _SessionLocal is None:
        with _session_lock:
            if _SessionLocal is None:
                _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())

    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(db_url: Optional[str] = None):
    """Initialize database tables."""
    engine = get_engine(db_url)

    # Import all models to register them with SQLAlchemy metadata (side-effect imports)
    from .models import Campaign, SMTPServer, Template, RecipientList, Recipient, EmailLog

    _ = (Campaign, SMTPServer, Template, RecipientList, Recipient, EmailLog)  # register metadata

    Base.metadata.create_all(bind=engine)
    return engine


def get_session_direct() -> Session:
    """Get a direct session (caller must close)."""
    global _SessionLocal

    if _SessionLocal is None:
        with _session_lock:
            if _SessionLocal is None:
                _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())

    return _SessionLocal()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for a database session.

    Replaces the ``session = get_session_direct(); try: ... finally: session.close()``
    pattern used throughout the codebase. On unhandled exceptions the session
    is rolled back before close to avoid leaving a poisoned transaction.

    Example:
        with session_scope() as session:
            repo = CampaignRepository(session)
            return repo.get_recent(10)
    """
    session = get_session_direct()
    try:
        yield session
    except Exception:
        try:
            session.rollback()
        except Exception:
            # The original error still propagates via `raise` below; surface
            # the rollback failure too rather than losing it entirely.
            logger.warning("session.rollback() failed during exception handling", exc_info=True)
        raise
    finally:
        session.close()
