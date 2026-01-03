"""Tests for Web API endpoints."""

import pytest
from unittest.mock import patch, Mock, MagicMock, mock_open
from flask import json
from mercury.web.app import create_app

@pytest.fixture
def api_app():
    """Create app for API tests."""
    with patch('mercury.web.app.init_auth'), \
         patch('mercury.web.app.get_app_context') as mock_ctx_getter, \
         patch('mercury.web.app.register_auth_routes'), \
         patch('mercury.web.app.limiter') as mock_limiter, \
         patch('mercury.web.app.api_key_or_login_required', side_effect=lambda f: f):
        
        # Configure mock context limiter
        mock_ctx = Mock()
        mock_ctx.limiter.limit.side_effect = lambda limit_string: lambda f: f
        mock_ctx_getter.return_value = mock_ctx
        
        app = create_app()
        app.config['SECRET_KEY'] = 'test-key'
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['TESTING'] = True
        return app

@pytest.fixture
def auth_client(api_app):
    """Authenticated client."""
    return api_app.test_client()

# /api/status

def test_api_status(auth_client):
    response = auth_client.get('/api/status')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'ok'

# /api/campaigns

def test_api_list_campaigns(auth_client):
    with patch('mercury.services.campaign_service.CampaignService') as MockService:
        service = MockService.return_value
        campaign = Mock()
        campaign.to_dict.return_value = {'id': 1, 'name': 'Test'}
        service.list_campaigns.return_value = [campaign]
        
        response = auth_client.get('/api/campaigns')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['campaigns']) == 1
        assert data['campaigns'][0]['name'] == 'Test'

def test_api_create_campaign(auth_client):
    with patch('mercury.services.campaign_service.CampaignService') as MockService:
        service = MockService.return_value
        campaign = Mock()
        campaign.to_dict.return_value = {'id': 1, 'name': 'New'}
        service.create_campaign.return_value = campaign
        
        payload = {'name': 'New', 'subject': 'Hi'}
        response = auth_client.post('/api/campaigns', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['campaign']['name'] == 'New'

def test_api_create_campaign_validation(auth_client):
    response = auth_client.post('/api/campaigns', json={})
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data

# /api/smtp

def test_api_list_smtp(auth_client):
    with patch('mercury.data.repositories.SMTPRepository') as MockRepo, \
         patch('mercury.data.database.get_session_direct'):
        
        repo = MockRepo.return_value
        server = Mock()
        server.to_dict.return_value = {'host': 'smtp.test'}
        repo.get_all.return_value = [server]
        
        response = auth_client.get('/api/smtp')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['servers']) == 1
        assert data['servers'][0]['host'] == 'smtp.test'

def test_api_add_smtp(auth_client):
    with patch('mercury.services.smtp_service.SMTPService') as MockService:
        service = MockService.return_value
        server = Mock()
        server.to_dict.return_value = {'host': 'new.smtp'}
        service.add_server.return_value = server
        
        payload = {'host': 'new.smtp', 'port': 25}
        response = auth_client.post('/api/smtp', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

def test_api_test_smtp(auth_client):
    with patch('mercury.data.repositories.SMTPRepository') as MockRepo, \
         patch('mercury.services.smtp_service.SMTPService') as MockService, \
         patch('mercury.data.database.get_session_direct'):
        
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
        
        # Patch asyncio loop to avoid issues
        with patch('asyncio.new_event_loop') as mock_new_loop, \
             patch('asyncio.set_event_loop'):
             
             mock_loop = Mock()
             mock_new_loop.return_value = mock_loop
             mock_loop.run_until_complete.side_effect = lambda coro: {'success': True, 'server': 'primary'}
             
             response = auth_client.post('/api/smtp/test/primary')
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

# /api/templates

def test_api_list_templates(auth_client):
    with patch('mercury.data.repositories.TemplateRepository') as MockRepo, \
         patch('mercury.data.database.get_session_direct'):
         
        repo = MockRepo.return_value
        tpl = Mock()
        tpl.to_dict.return_value = {'name': 'T1'}
        repo.get_active.return_value = [tpl]
        
        response = auth_client.get('/api/templates')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert len(data['templates']) == 1

def test_api_preview_template(auth_client):
    with patch('mercury.features.template_engine.TemplateEngine') as MockEngine:
        engine = MockEngine.return_value
        engine.preview.return_value = "<html>Preview</html>"
        engine.get_used_placeholders.return_value = ["name"]
        
        payload = {'html': '<h1>Hi</h1>', 'recipient': 'a@b.com'}
        response = auth_client.post('/api/templates/preview', json=payload)
        
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['html'] == "<html>Preview</html>"
        assert data['placeholders'] == ["name"]

# /api/logs & /api/stats

def test_api_logs(auth_client):
    with patch('os.path.exists') as mock_exists, \
         patch('builtins.open', new_callable=mock_open, read_data="a\nb\n") as mock_file:
        
        mock_exists.return_value = True
        
        # Success logs
        resp = auth_client.get('/api/logs/success')
        assert resp.status_code == 200
        assert len(json.loads(resp.data)['emails']) == 2
        
        # Failed logs
        resp = auth_client.get('/api/logs/failed')
        assert resp.status_code == 200
        assert len(json.loads(resp.data)['failures']) == 2

def test_api_stats(auth_client):
     with patch('os.path.exists') as mock_exists, \
          patch('builtins.open', new_callable=mock_open) as mock_file:
        
        # Test needs careful mocking of open since it opens two different files.
        # But for stats, it likely reads both.
        # mock_open reads same data for all opens unless configured with side_effect.
        
        mock_exists.return_value = True
        mock_file.side_effect = [
            mock_open(read_data="a\nb\n").return_value, # success
            mock_open(read_data="x\n").return_value     # failed
        ]
        
        resp = auth_client.get('/api/stats')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        # 2 success, 1 failed
        assert data['total_sent'] == 2
        assert data['total_failed'] == 1
        assert data['total_attempts'] == 3



