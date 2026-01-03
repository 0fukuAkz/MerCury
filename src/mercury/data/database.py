"""Database configuration and session management."""

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

Base = declarative_base()

_engine = None
_SessionLocal = None


def get_engine(db_url: str = None):
    """Get or create database engine."""
    global _engine
    
    if _engine is None:
        if db_url is None:
            db_path = os.environ.get("DATABASE_URL", "sqlite:///logs/mercury.db")
        else:
            db_path = db_url
        
        _engine = create_engine(
            db_path,
            connect_args={"check_same_thread": False} if "sqlite" in db_path else {},
            echo=os.environ.get("SQL_DEBUG", "").lower() == "true"
        )
    
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Get database session as context manager."""
    global _SessionLocal
    
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
    
    # Import all models to register them
    from .models import (
        Campaign, SMTPServer, Template, RecipientList, Recipient, EmailLog
    )
    
    Base.metadata.create_all(bind=engine)
    return engine


def get_session_direct() -> Session:
    """Get a direct session (caller must close)."""
    global _SessionLocal
    
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    
    return _SessionLocal()

