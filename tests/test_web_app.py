"""Tests for the Flask Web Application."""

import pytest
from unittest.mock import Mock, patch
from flask import Flask, session
from unified_sender.web.app import create_app, register_auth_routes, register_routes

from unified_sender.app_context import AppContext
from unified_sender.data.models.user import User

@pytest.fixture
def mock_app_context():
    """Create a mock application context."""
    ctx = Mock(spec=AppContext)
    
    # Mock services
    ctx.campaign_service = Mock()
    ctx.smtp_service = Mock()
    ctx.template_service = Mock()
    ctx.recipient_service = Mock()
    ctx.scheduler_service = Mock()
    ctx.tracking_service = Mock()
    ctx.auth = Mock()
    ctx.db_session = Mock()
    
    # Mock database queries
    ctx.db_session.query.return_value = Mock()

    # CRITICAL: Mock limiter.limit to be a pass-through decorator
    # Otherwise it returns a Mock which confuses @wraps and causes endpoint collisions
    ctx.limiter.limit.side_effect = lambda *args, **kwargs: lambda func: func
    
    return ctx

def test_app_creation(mock_app_context):
    """Test app creation works manually."""
    app = create_app(config={'TESTING': True, 'WTF_CSRF_ENABLED': False}, app_context=mock_app_context)
    assert app is not None
    client = app.test_client()
    resp = client.get('/login')
    assert resp.status_code == 200

@pytest.fixture
def flask_app(mock_app_context):
    app = create_app(config={
        'TESTING': True,
        'SECRET_KEY': 'test_key',
        'WTF_CSRF_ENABLED': False
    }, app_context=mock_app_context)
    yield app

@pytest.fixture
def client(flask_app):
    return flask_app.test_client()

@pytest.fixture
def auth_client(client, flask_app):
    """Authenticated client."""
    # Patch get_user_by_id to allow user_loader to work
    with patch('unified_sender.security.auth.get_user_by_id') as mock_get_user:
        # Use auth.User not model User for Flask-Login
        from unified_sender.security.auth import User as AuthUser
        user = AuthUser(id="1", username="admin", password_hash="hash", is_admin=True)
        mock_get_user.return_value = user
        
        with client.session_transaction() as sess:
            sess['_user_id'] = "1"
        yield client

@pytest.fixture(autouse=True)
def mock_user_loader():
    """Ensure get_user_by_id is mocked for all tests to support Flask-Login."""
    with patch('unified_sender.security.auth.get_user_by_id') as mock_get:
        # Default behavior: return a valid admin user for ID "1"
        from unified_sender.security.auth import User as AuthUser
        user = AuthUser(id="1", username="admin", password_hash="hash", is_admin=True)
        mock_get.side_effect = lambda uid: user if str(uid) == "1" else None
        yield mock_get

class TestAuth:
    """Test authentication routes."""
    
    def test_login_page_loads(self, client):
        """Test login page renders."""
        response = client.get('/login')
        assert response.status_code == 200
        assert b"Login" in response.data

    def test_login_success(self, client):
        """Test successful login."""
        # Patch authenticate in app.py
        with patch('unified_sender.web.app.authenticate') as mock_auth:
            # Mock successful auth
            from unified_sender.security.auth import User as AuthUser
            user = AuthUser(id="1", username="admin", password_hash="hash", is_admin=True)
            mock_auth.return_value = user
            
            response = client.post('/login', data={
                'username': 'admin',
                'password': 'password'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            assert b"Dashboard" in response.data
            
            # Verify call
            mock_auth.assert_called_with('admin', 'password')

    def test_login_failure(self, client):
        """Test failed login."""
        with patch('unified_sender.web.app.authenticate') as mock_auth:
            mock_auth.return_value = None
            
            response = client.post('/login', data={
                'username': 'admin',
                'password': 'wrong'
            }, follow_redirects=True)
            
            assert response.status_code == 200
            assert b"Invalid username or password" in response.data

    def test_logout(self, auth_client):
        """Test logout."""
        response = auth_client.get('/logout', follow_redirects=True)
        assert response.status_code == 200
        assert b"Login" in response.data


class TestRoutes:
    """Test main UI routes."""
    
    def test_index_redirects_if_unauth(self, client):
        """Test unauthenticated access redirects to login."""
        response = client.get('/')
        assert response.status_code == 302
        assert "login" in response.location

    def test_index_loads(self, auth_client):
        """Test dashboard loads."""
        response = auth_client.get('/')
        assert response.status_code == 200
        # Check for text present in base.html sidebar or index.html title
        assert b"Unified Sender" in response.data
        assert b"Dashboard" in response.data

    def test_campaigns_page(self, auth_client):
        """Test campaigns page."""
        response = auth_client.get('/campaigns')
        assert response.status_code == 200
        assert b"Campaigns" in response.data

    def test_new_campaign_page(self, auth_client):
        """Test new campaign page."""
        response = auth_client.get('/campaigns/new')
        assert response.status_code == 200
        assert b"New Campaign" in response.data

    def test_smtp_page(self, auth_client):
        """Test SMTP page."""
        response = auth_client.get('/smtp')
        assert response.status_code == 200
        assert b"SMTP Servers" in response.data

    def test_templates_page(self, auth_client):
        """Test templates page."""
        response = auth_client.get('/templates')
        assert response.status_code == 200
        assert b"Email Templates" in response.data

    def test_recipients_page(self, auth_client):
        """Test recipients page."""
        response = auth_client.get('/recipients')
        assert response.status_code == 200
        assert b"Recipients" in response.data

    def test_logs_page(self, auth_client):
        """Test logs page."""
        response = auth_client.get('/logs')
        assert response.status_code == 200
        # logs.html checking, assume title is Logs
        # assert b"Logs" in response.data


class TestAPI:
    """Test API routes."""

    def test_api_status(self, client):
        """Test public status endpoint."""
        response = client.get('/api/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'

    def test_api_campaigns_unauth(self, client):
        """Test API requires auth."""
        response = client.get('/api/campaigns')
        assert response.status_code in [401, 403, 302]
