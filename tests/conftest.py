"""Pytest configuration and shared fixtures."""

import logging
import pytest
import asyncio
from typing import AsyncGenerator, Generator
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(autouse=True)
def _restore_log_propagation():
    """Ensure mercury.* loggers can be captured by caplog before each test.

    Other tests (and app-fixture init via configure_logging) can leave loggers
    in states that prevent pytest's caplog fixture from capturing records:
    propagate=False, disabled=True, or a level filter above WARNING. Restore
    a clean state before each test runs.
    """
    # Undo any global logging.disable() set by an earlier test.
    logging.disable(logging.NOTSET)
    for name in list(logging.root.manager.loggerDict.keys()):
        if name == 'mercury' or name.startswith('mercury.'):
            lg = logging.getLogger(name)
            lg.propagate = True
            lg.disabled = False
            if lg.level > logging.WARNING and lg.level != logging.NOTSET:
                lg.setLevel(logging.NOTSET)
    yield

from mercury.data.database import Base
from mercury.data.models import User, Template, SMTPServer, Recipient, Campaign
from mercury.engine.connection_pool import SMTPServerConfig, AsyncConnectionPool
from mercury.engine.rate_limiter import RateLimiter, RateLimiterConfig
from mercury.engine.retry_queue import RetryQueue, RetryConfig


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
#     if tasks:
#         await asyncio.gather(*tasks, return_exceptions=True)


# Web Fixtures

@pytest.fixture
def app(db_engine):
    """Create Flask application fixture."""
    from mercury.web.app import create_app
    from unittest.mock import patch, MagicMock
    from mercury.app_context import AppContext
    import os
    
    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()

    # Create a factory for sessions bound to the test engine
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=db_engine)

    # Patch DB init and Admin creation. Patching `get_session_direct` at its
    # *source* module is sufficient for the api package because routes now
    # call `session_scope()` which does runtime lookup. Per-submodule
    # patches remain for callers that still snapshot the function at import
    # time (services, web.app, web.routes.templates).
    with patch('mercury.web.app.init_db'), \
         patch('mercury.web.app.UserRepository') as MockRepo, \
         patch('mercury.web.app.get_app_context', return_value=mock_context), \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.app.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.identity_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.settings_service.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):
         
        MockRepo.return_value.get_admins.return_value = [MagicMock()]
        
        app = create_app(config={'TESTING': True, 'WTF_CSRF_ENABLED': False})
        yield app

@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()

@pytest.fixture
def admin_user(db_session):
    """Create and return an admin user."""
    from mercury.security.auth import hash_password
    u = User(username="admin", email="admin@test.com", is_admin=True, is_active=True)
    u.password_hash = hash_password("password")
    u.api_key = "test_api_key"
    try:
        db_session.add(u)
        db_session.commit()
    except Exception:
        db_session.rollback()
        # User might already exist if session shared or cleanup failed
        # Retrieve existing
        u = db_session.query(User).filter_by(username="admin").first()
    return u

@pytest.fixture
def auth_headers(admin_user):
    """Return headers for authenticated API requests."""
    return {'X-API-Key': admin_user.api_key}

