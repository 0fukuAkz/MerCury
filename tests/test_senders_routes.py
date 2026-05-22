"""Tests for senders routes."""

import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def app_no_login(db_engine):
    """App fixture with LOGIN_DISABLED=True."""
    from mercury.web.app import create_app
    from mercury.app_context import AppContext

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    mock_context.is_initialized = False

    TestSession = sessionmaker(bind=db_engine)

    with patch('mercury.web.app.init_db'), \
         patch('mercury.security.auth.UserRepository') as MockRepo, \
         patch('mercury.web.app.get_app_context', return_value=mock_context), \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.api.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.identity_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.settings_service.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):

        MockRepo.return_value.get_admins.return_value = [MagicMock()]
        app = create_app(config={
            'TESTING': True, 'WTF_CSRF_ENABLED': False, 'LOGIN_DISABLED': True,
        })
        yield app


@pytest.fixture
def client_no_login(app_no_login):
    return app_no_login.test_client()


def test_senders_index(client_no_login):
    """Test senders dashboard loads."""
    response = client_no_login.get('/senders/')
    assert response.status_code == 200

def test_add_email(client_no_login, db_session):
    """Test adding a sender email."""
    response = client_no_login.post('/senders/emails', data={
        'email': 'sender@example.com',
        'tags': 'marketing, sales'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Email added successfully' in response.data

def test_add_email_validation(client_no_login):
    """Test adding email without providing email."""
    response = client_no_login.post('/senders/emails', data={
        'email': '',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Email is required.' in response.data

def test_toggle_email(client_no_login, db_session):
    """Test toggling email status."""
    from mercury.data.models import FromEmail
    identity = FromEmail(email='toggle@example.com', is_active=True)
    db_session.add(identity)
    db_session.commit()
    response = client_no_login.post(f'/senders/emails/{identity.id}/toggle', follow_redirects=True)
    assert response.status_code == 200

def test_delete_email(client_no_login, db_session):
    """Test deleting email."""
    from mercury.data.models import FromEmail
    identity = FromEmail(email='delete@example.com', is_active=True)
    db_session.add(identity)
    db_session.commit()
    ident_id = identity.id
    response = client_no_login.post(f'/senders/emails/{ident_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Email deleted.' in response.data

def test_add_name(client_no_login, db_session):
    """Test adding a sender name."""
    response = client_no_login.post('/senders/names', data={
        'name': 'Marketing Team',
        'tags': 'marketing'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Name added successfully' in response.data

def test_add_name_validation(client_no_login):
    """Test adding name without providing name."""
    response = client_no_login.post('/senders/names', data={
        'name': '',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Name is required.' in response.data

def test_toggle_name(client_no_login, db_session):
    """Test toggling name status."""
    from mercury.data.models import SenderName
    identity = SenderName(name='Toggle Name', is_active=True)
    db_session.add(identity)
    db_session.commit()
    response = client_no_login.post(f'/senders/names/{identity.id}/toggle', follow_redirects=True)
    assert response.status_code == 200

def test_delete_name(client_no_login, db_session):
    """Test deleting name."""
    from mercury.data.models import SenderName
    identity = SenderName(name='Delete Name', is_active=True)
    db_session.add(identity)
    db_session.commit()
    ident_id = identity.id
    response = client_no_login.post(f'/senders/names/{ident_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Name deleted.' in response.data
