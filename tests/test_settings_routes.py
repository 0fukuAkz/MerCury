"""Tests for settings routes."""

import pytest

def test_settings_index_get(client):
    """Test settings dashboard loads."""
    response = client.get('/settings/')
    assert response.status_code == 200
    # It should render settings form

def test_settings_update_success(client, db_session):
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
    
    response = client.post('/settings/', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Settings updated successfully' in response.data
    
    # Verify DB update
    from mercury.data.models import GlobalSetting
    setting_record = db_session.query(GlobalSetting).first()
    assert setting_record is not None
    assert setting_record.daily_limit == 5000

def test_settings_update_invalid(client):
    """Test updating settings with invalid input."""
    data = {
        'daily_limit': 'not_a_number', # This should trip the ValueError in int()
        'hourly_limit': '1000',
    }
    
    response = client.post('/settings/', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Invalid input' in response.data
