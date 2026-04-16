"""Tests for API routes coverage."""

import pytest
import json
from unittest.mock import patch, MagicMock
from mercury.data.models import Campaign, SMTPServer, Template, EmailLog, EmailStatus

def test_api_status(client):
    response = client.get('/api/status')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'ok'
    assert 'version' in data

def test_api_list_campaigns(client, admin_user, auth_headers):
    # This requires user to be logged in or api key
    response = client.get('/api/campaigns', headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'campaigns' in data

def test_api_create_campaign_invalid(client, auth_headers):
    response = client.post('/api/campaigns', headers=auth_headers, json={})
    assert response.status_code == 400
    assert 'Campaign name required' in response.data.decode()

@patch('mercury.services.campaign_service.CampaignService.create_campaign')
def test_api_create_campaign_valid(mock_create, client, auth_headers):
    mock_campaign = MagicMock()
    mock_campaign.id = 999
    mock_campaign.to_dict.return_value = {'id': 999, 'name': 'Test Campaign'}
    mock_create.return_value = mock_campaign
    
    response = client.post('/api/campaigns', headers=auth_headers, json={
        'name': 'Test Campaign',
        'subjects': ['Hello'],
        'from_names': ['Sales']
    })
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True
    assert data['campaign']['name'] == 'Test Campaign'

def test_api_list_smtp(client, auth_headers, db_session):
    # Add a mock SMTP server to DB
    server = SMTPServer(name="Test SMTP", host="smtp.example.com", is_enabled=True)
    db_session.add(server)
    db_session.commit()
    
    response = client.get('/api/smtp', headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['servers']) > 0

def test_api_add_smtp_invalid(client, auth_headers):
    response = client.post('/api/smtp', headers=auth_headers, json={})
    assert response.status_code == 400

@patch('mercury.services.smtp_service.SMTPService.add_server')
def test_api_add_smtp_valid(mock_add, client, auth_headers):
    mock_server = MagicMock()
    mock_server.to_dict.return_value = {'id': 1, 'host': 'smtp.example.com'}
    mock_add.return_value = mock_server
    
    response = client.post('/api/smtp', headers=auth_headers, json={'host': 'smtp.example.com'})
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

@patch('mercury.services.smtp_service.SMTPService.test_connection')
def test_api_test_smtp(mock_test, client, auth_headers, db_session):
    mock_test.return_value = {'success': True}
    server = SMTPServer(name="TestSMTP", host="smtp.example.com", is_enabled=True)
    db_session.add(server)
    db_session.commit()
    
    response = client.post('/api/smtp/test/TestSMTP', headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

def test_api_list_templates(client, auth_headers, db_session):
    t = Template(name="API Template", subject="Hello", html_content="World")
    db_session.add(t)
    db_session.commit()
    
    response = client.get('/api/templates', headers=auth_headers)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['templates']) > 0

def test_api_preview_template(client, auth_headers):
    response = client.post('/api/templates/preview', headers=auth_headers, json={
        'html': 'Hello {{ name }}',
        'placeholders': {'name': 'Alice'}
    })
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'Hello Alice' in data['html']

def test_api_logs(client, auth_headers, db_session):
    from datetime import datetime, UTC
    # Add some logs
    log1 = EmailLog(recipient_email="success@example.com", status=EmailStatus.SENT, sent_at=datetime.now(UTC))
    log2 = EmailLog(recipient_email="fail@example.com", status=EmailStatus.FAILED, error_message="Error", failed_at=datetime.now(UTC))
    db_session.add(log1)
    db_session.add(log2)
    db_session.commit()
    
    response_s = client.get('/api/logs/success', headers=auth_headers)
    assert response_s.status_code == 200
    
    response_f = client.get('/api/logs/failed', headers=auth_headers)
    assert response_f.status_code == 200

def test_api_stats(client, auth_headers):
    response = client.get('/api/stats', headers=auth_headers)
    assert response.status_code == 200

def test_api_list_webhooks(client, auth_headers):
    response = client.get('/api/webhooks', headers=auth_headers)
    assert response.status_code == 200

def test_api_register_webhook(client, auth_headers):
    response = client.post('/api/webhooks', headers=auth_headers, json={'url': 'http://example.com', 'events': ['sent']})
    assert response.status_code == 200

@patch('mercury.services.webhook_service.WebhookService.unregister_webhook')
def test_api_delete_webhook(mock_delete, client, auth_headers):
    response = client.delete('/api/webhooks/1', headers=auth_headers)
    assert response.status_code == 200

@patch('mercury.services.scheduler_service.SchedulerService.get_all_jobs')
def test_api_scheduling(mock_get_all, client, auth_headers):
    mock_get_all.return_value = []
    
    response = client.get('/api/scheduling/jobs', headers=auth_headers)
    assert response.status_code == 200
    
    response_cancel = client.delete('/api/scheduling/jobs/123', headers=auth_headers)
    assert response_cancel.status_code == 200

@patch('mercury.services.scheduler_service.SchedulerService.schedule_once')
def test_api_scheduling_create_once(mock_once, client, auth_headers):
    mock_job = MagicMock()
    mock_job.to_dict.return_value = {'id': '123'}
    mock_once.return_value = mock_job
    
    response = client.post('/api/scheduling/jobs', headers=auth_headers, json={
        'name': 'Job', 'campaign_id': 1, 'schedule_type': 'once', 'run_at': '2026-01-01T00:00:00'
    })
    assert response.status_code == 200

def test_api_scheduling_create_invalid(client, auth_headers):
    response = client.post('/api/scheduling/jobs', headers=auth_headers, json={})
    assert response.status_code == 400

@patch('mercury.services.bounce_service.BounceService.get_suppression_list')
def test_api_bounces(mock_sup, client, auth_headers):
    mock_sup.return_value = []
    response = client.get('/api/bounces/suppression', headers=auth_headers)
    assert response.status_code == 200
    
    response_add = client.post('/api/bounces/suppression', headers=auth_headers, json={'email': 'bounce@exp.com'})
    assert response_add.status_code == 200

    response_rm = client.delete('/api/bounces/suppression/bounce@exp.com', headers=auth_headers)
    assert response_rm.status_code == 200

@patch('mercury.services.dead_letter_service.DeadLetterService.get_statistics')
def test_api_dead_letter(mock_stats, client, auth_headers):
    mock_stats.return_value = {}
    response = client.get('/api/dead-letter/stats', headers=auth_headers)
    assert response.status_code == 200
