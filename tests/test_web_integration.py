
import pytest
import json
import os
from unittest.mock import MagicMock, patch
from flask import Flask

from mercury.web.app import create_app
from mercury.app_context import AppContext
from mercury.data.models import User, Campaign, SMTPServer
from mercury.security.auth import hash_password

@pytest.fixture
def app_with_context(db_engine, db_session):
    """Create Flask app with mock context and DB session."""
    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    # Allow rate limiter to pass through
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    
    # Create a factory for sessions bound to the test engine
    # This ensures app gets NEW sessions but they share the same memory DB
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=db_engine)
    
    # We need to patch get_app_context because accessible globally
    with patch('mercury.web.app.get_app_context', return_value=mock_context), \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.api.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.app.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):
        
        # Patch init_db inside create_app to avoid recreating tables
        with patch('mercury.data.database.init_db'):
             app = create_app(config={'TESTING': True, 'WTF_CSRF_ENABLED': False}, app_context=mock_context)
             
             # Also patch dependencies used in routes import
             # This is tricky because routes import services which might init things
             # We rely on mocks inside tests or service factories
             
             yield app

@pytest.fixture
def client(app_with_context):
    return app_with_context.test_client()

@pytest.fixture
def admin_user(db_session):
    u = User(username="admin", email="admin@test.com", is_admin=True, is_active=True)
    u.password_hash = hash_password("password")
    u.api_key = "test_api_key"
    db_session.add(u)
    db_session.commit()
    return u

@pytest.fixture
def auth_headers(admin_user):
    return {'X-API-Key': admin_user.api_key}

class TestWebIntegration:
    
    def test_api_status(self, client):
        resp = client.get('/api/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'

    def test_api_auth_required(self, client):
        resp = client.get('/api/campaigns')
        assert resp.status_code == 401

    def test_api_auth_success(self, client, auth_headers):
        # Starts with no campaigns
        resp = client.get('/api/campaigns', headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.get_json()['campaigns'], list)

    def test_campaign_create(self, client, auth_headers):
        import uuid
        name = f"Test Campaign {uuid.uuid4()}"
        payload = {
            "name": name,
            "subject": "Hello",
            "from_email": "sender@test.com",
            "dry_run": True
        }
        resp = client.post('/api/campaigns', json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['campaign']['name'] == name

    def test_smtp_management(self, client, auth_headers):
        # Add server
        import uuid
        uid = str(uuid.uuid4())
        host = f"smtp.{uid}.com"
        name = f"Test SMTP {uid}"
        payload = {
            "host": host,
            "name": name,
            "port": 587
        }
        resp = client.post('/api/smtp', json=payload, headers=auth_headers)
        assert resp.status_code == 200
        
        # List servers
        resp = client.get('/api/smtp', headers=auth_headers)
        assert resp.status_code == 200
        servers = resp.get_json()['servers']
        assert any(s['host'] == host for s in servers)

    def test_stats_endpoint(self, client, auth_headers):
        resp = client.get('/api/stats', headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'total_sent' in data
        assert 'success_rate' in data

    def test_logs_endpoint_db(self, client, auth_headers):
        resp = client.get('/api/logs/success', headers=auth_headers)
        assert resp.status_code == 200
        assert 'emails' in resp.get_json()

    def test_webhook_register(self, client, auth_headers):
        payload = {
            "url": "http://webhook.com",
            "events": ["sent", "failed"]
        }
        resp = client.post('/api/webhooks', json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
