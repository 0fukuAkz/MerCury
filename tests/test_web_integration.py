
import pytest
import json
import os
from unittest.mock import MagicMock, patch
from flask import Flask

from mercury.web.app import create_app
from mercury.app_context import AppContext
from mercury.data.models import User, Campaign, SMTPServer
from mercury.security.auth import hash_password

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
