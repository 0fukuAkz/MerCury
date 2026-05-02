"""Tests for Web API endpoints."""

import pytest
from unittest.mock import patch, Mock, MagicMock
from flask import json
from mercury.web.app import create_app

@pytest.fixture(autouse=True)
def mock_auth_api():
    """Mock authentication for all API tests."""
    with patch('flask_login.utils._get_user') as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user_getter.return_value = mock_user
        # Also mock decorators.current_user if used directly
        with patch('mercury.web.decorators.current_user', mock_user):
            yield mock_user

# /api/status

def test_api_status(client):
    response = client.get('/api/status')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'ok'

# /api/campaigns

def test_api_list_campaigns(client):
    # The route reads via CampaignRepository.get_recent(), not CampaignService —
    # patch the actual call site.
    with patch('mercury.web.routes.api.CampaignRepository') as MockRepo:
        repo = MockRepo.return_value
        campaign = Mock()
        campaign.to_dict.return_value = {'id': 1, 'name': 'Test'}
        repo.get_recent.return_value = [campaign]

        response = client.get('/api/campaigns')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['campaigns']) == 1
        assert data['campaigns'][0]['name'] == 'Test'

def test_api_create_campaign(client):
    with patch('mercury.web.routes.api.CampaignService') as MockService:
        service = MockService.return_value
        campaign = Mock()
        campaign.id = 999
        campaign.to_dict.return_value = {'id': 999, 'name': 'New'}
        service.create_campaign.return_value = campaign
        
        payload = {'name': 'New', 'subject': 'Hi'}
        response = client.post('/api/campaigns', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['campaign']['name'] == 'New'

def test_api_create_campaign_validation(client):
    response = client.post('/api/campaigns', json={})
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data

# /api/smtp

def test_api_list_smtp(client):
    with patch('mercury.web.routes.api.SMTPRepository') as MockRepo:
        repo = MockRepo.return_value
        server = Mock()
        server.to_dict.return_value = {'host': 'smtp.test'}
        repo.get_all.return_value = [server]
        
        response = client.get('/api/smtp')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['servers']) == 1
        assert data['servers'][0]['host'] == 'smtp.test'

def test_api_add_smtp(client):
    with patch('mercury.web.routes.api.SMTPService') as MockService:
        service = MockService.return_value
        server = Mock()
        server.to_dict.return_value = {'host': 'new.smtp'}
        service.add_server.return_value = server
        
        payload = {'host': 'new.smtp', 'port': 25}
        response = client.post('/api/smtp', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

def test_api_test_smtp(client):
    with patch('mercury.web.routes.api.SMTPRepository') as MockRepo, \
         patch('mercury.web.routes.api.SMTPService') as MockService:
        
        # Mock Repo
        repo = MockRepo.return_value
        server = Mock()
        repo.get_all.return_value = [server]
        
        # Mock Service
        service = MockService.return_value
        # Mock async test_connection
        async def mock_test(name):
             return {'success': True, 'server': name}
        service.test_connection.side_effect = mock_test
        
        with patch('asyncio.new_event_loop') as mock_new_loop, \
             patch('asyncio.set_event_loop'):
             
             mock_loop = Mock()
             mock_new_loop.return_value = mock_loop
             mock_loop.run_until_complete.side_effect = lambda coro: {'success': True, 'server': 'primary'}
             
             response = client.post('/api/smtp/test/primary')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

# /api/templates

def test_api_list_templates(client):
    with patch('mercury.web.routes.api.TemplateRepository') as MockRepo:
        repo = MockRepo.return_value
        tpl = Mock()
        tpl.to_dict.return_value = {'name': 'T1'}
        repo.get_active.return_value = [tpl]
        
        response = client.get('/api/templates')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['templates']) == 1

def test_api_preview_template(client):
    with patch('mercury.web.routes.api.TemplateEngine') as MockEngine:
        engine = MockEngine.return_value
        engine.preview.return_value = "<html>Preview</html>"
        engine.get_used_placeholders.return_value = ["name"]
        
        payload = {'html': '<h1>Hi</h1>', 'recipient': 'a@b.com'}
        response = client.post('/api/templates/preview', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['html'] == "<html>Preview</html>"
        assert data['placeholders'] == ["name"]

# /api/logs & /api/stats

def test_api_logs(client):
    with patch('mercury.web.routes.api.LogRepository') as MockRepo:
        MockRepo.return_value.get_recent_success.return_value = [
            MagicMock(recipient_email='a'), MagicMock(recipient_email='b')
        ]
        MockRepo.return_value.get_recent_failed.return_value = [
            MagicMock(recipient_email='x', error_message='err', failed_at=MagicMock(isoformat=lambda: 'now')), 
            MagicMock(recipient_email='y', error_message='err', failed_at=MagicMock(isoformat=lambda: 'now'))
        ]
        
        # Success logs
        resp = client.get('/api/logs/success')
        assert resp.status_code == 200
        assert len(json.loads(resp.data)['emails']) == 2
        
        # Failed logs
        resp = client.get('/api/logs/failed')
        assert resp.status_code == 200
        assert len(json.loads(resp.data)['failures']) == 2

def test_api_stats(client):
     with patch('mercury.web.routes.api.LogRepository') as MockRepo:
        MockRepo.return_value.get_global_stats.return_value = {
            'total_sent': 2, 'total_failed': 1, 'total_attempts': 3
        }
        
        resp = client.get('/api/stats')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['total_sent'] == 2
        assert data['total_failed'] == 1
        assert data['total_attempts'] == 3
