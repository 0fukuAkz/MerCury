"""Tests for settings routes."""

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


def test_settings_index_get(client_no_login):
    """Test settings dashboard loads."""
    response = client_no_login.get('/settings/')
    assert response.status_code == 200

def test_settings_update_success(client_no_login, db_session):
    """Test updating settings."""
    data = {
        'daily_limit': '5000',
        'hourly_limit': '1000',
        'min_delay': '1.5',
        'max_delay': '3.0',
        'default_reply_to': 'reply@example.com',
        'max_retries': '5',
        'retry_delay_base': '600',
        'smtp_timeout': '45',
        'max_concurrency': '10',
        'dns_timeout': '10',
        'proxy_enabled': 'on',
        'proxy_list': 'http://proxy.example.com:8080\nhttp://proxy2.example.com:8080',
        'batch_size': '500',
        'default_sender_name': 'Default Sender',
        'default_test_email': 'test@test.com',
        'log_retention_days': '60',
        'log_level': 'DEBUG',
        'ui_theme': 'light'
    }
    response = client_no_login.post('/settings/', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Settings updated successfully' in response.data

def test_settings_update_invalid(client_no_login):
    """Test updating settings with invalid input."""
    data = {
        'daily_limit': 'not_a_number',
        'hourly_limit': '1000',
    }
    response = client_no_login.post('/settings/', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Invalid input' in response.data
