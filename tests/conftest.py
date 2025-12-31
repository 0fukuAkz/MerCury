"""Pytest configuration and shared fixtures."""

import pytest
import asyncio
from typing import AsyncGenerator, Generator
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from unified_sender.data.database import Base
from unified_sender.data.models import User, Template, SMTPServer, Recipient, Campaign
from unified_sender.engine.connection_pool import SMTPServerConfig, AsyncConnectionPool
from unified_sender.engine.rate_limiter import RateLimiter, RateLimiterConfig
from unified_sender.engine.retry_queue import RetryQueue, RetryConfig


# Database Fixtures

@pytest.fixture(scope="function")
def db_engine():
    """Create in-memory SQLite database engine."""
    from sqlalchemy.pool import StaticPool
    engine = create_engine(
        "sqlite:///:memory:", 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool,
        echo=False
    )
    print(f"DEBUG: Registered tables: {Base.metadata.tables.keys()}")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """Create database session."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# SMTP Fixtures

@pytest.fixture
def smtp_config() -> SMTPServerConfig:
    """Create test SMTP configuration."""
    return SMTPServerConfig(
        name="test-smtp",
        host="smtp.example.com",
        port=587,
        username="test@example.com",
        password="testpass123",
        use_tls=True,
        max_per_minute=60,
        max_per_hour=1000
    )


@pytest.fixture
async def smtp_pool(smtp_config) -> AsyncGenerator[AsyncConnectionPool, None]:
    """Create async SMTP connection pool."""
    pool = AsyncConnectionPool(smtp_config, pool_size=2)
    await pool.initialize()
    yield pool
    await pool.close_all()


# Rate Limiter Fixtures

@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Create rate limiter for testing."""
    config = RateLimiterConfig(per_minute=60, per_hour=1000)
    return RateLimiter(config)


# Retry Queue Fixtures

@pytest.fixture
async def retry_queue() -> AsyncGenerator[RetryQueue, None]:
    """Create retry queue for testing."""
    config = RetryConfig(
        max_attempts=3,
        base_delay=0.1,  # Fast retries for testing
        max_delay=1.0,
        concurrency=5,
        process_interval=0.1
    )
    queue = RetryQueue(config)
    await queue.start()
    yield queue
    await queue.stop()


# Template Fixtures

@pytest.fixture
def sample_html_template() -> str:
    """Sample HTML template for testing."""
    return """
    <html>
    <body>
        <h1>Hello {{first_name}}!</h1>
        <p>Email: {{email}}</p>
        {{if:link}}
        <a href="{{link}}">Click here</a>
        {{endif}}
    </body>
    </html>
    """


@pytest.fixture
def sample_recipients() -> list[dict]:
    """Sample recipient data."""
    return [
        {"email": "user1@example.com", "first_name": "John", "company": "Acme"},
        {"email": "user2@example.com", "first_name": "Jane", "company": "TechCorp"},
        {"email": "user3@example.com", "first_name": "Bob", "company": "StartupXYZ"},
    ]


# Event Loop Configuration

# Disabled on Windows - causes hanging
# @pytest.fixture(scope="session")
# def event_loop_policy():
#     """Set event loop policy for async tests."""
#     return asyncio.get_event_loop_policy()


# Cleanup - disabled on Windows
# @pytest.fixture(autouse=True)
# async def cleanup_tasks():
#     """Clean up pending tasks after each test."""
#     yield
#     # Cancel all pending tasks
#     tasks = [t for t in asyncio.all_tasks() if not t.done()]
#     for task in tasks:
#         task.cancel()
#     if tasks:
#         await asyncio.gather(*tasks, return_exceptions=True)

