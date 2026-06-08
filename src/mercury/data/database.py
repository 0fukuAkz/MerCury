"""Database configuration and session management."""

import os
import threading
from contextlib import contextmanager
from typing import Generator, Iterator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

Base = declarative_base()

_engine = None
_SessionLocal = None
_engine_lock = threading.Lock()
_session_lock = threading.Lock()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in dbapi_connection.__class__.__module__.lower():
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine(db_url: str = None):
    """Get or create database engine."""
    global _engine

    if _engine is None:
        with _engine_lock:
            if _engine is None:
                if db_url is None:
                    # Use app_dirs to determine correct path (local or system user data)
                    from mercury.utils.app_dirs import get_db_path

                    db_path = get_db_path()
                else:
                    db_path = db_url

                _engine = create_engine(
                    db_path,
                    connect_args={"check_same_thread": False} if "sqlite" in db_path else {},
                    echo=os.environ.get("SQL_DEBUG", "").lower() == "true",
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


def init_db(db_url: str = None):
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
            pass
        raise
    finally:
        session.close()
