from unittest.mock import MagicMock, patch

class TestApiExtended:
    def test_list_campaigns_empty(self, client, auth_headers):
        with patch('mercury.web.routes.api.campaigns.CampaignService') as MockService:
            MockService.return_value.list_campaigns.return_value = []
            resp = client.get('/api/campaigns', headers=auth_headers)
            assert resp.status_code == 200
            assert resp.get_json()['campaigns'] == []

    def test_list_templates(self, client, auth_headers):
        with patch('mercury.web.routes.api.templates.TemplateRepository') as MockRepo:
            t = MagicMock()
            t.to_dict.return_value = {'id': 1, 'name': 'T1'}
            MockRepo.return_value.get_active.return_value = [t]
            
            resp = client.get('/api/templates', headers=auth_headers)
            assert resp.status_code == 200
            assert resp.get_json()['templates'][0]['name'] == 'T1'

    def test_preview_template(self, client, auth_headers):
        # API expects html raw content for preview, not ID
        payload = {
            "html": "Hello {{name}}",
            "placeholders": {"name": "Test"}
        }
        with patch('mercury.web.routes.api.templates.TemplateEngine') as MockEngine:
            MockEngine.return_value.preview.return_value = "Hello Test"
            MockEngine.return_value.get_used_placeholders.return_value = ['name']
            
            resp = client.post('/api/templates/preview', json=payload, headers=auth_headers)
            assert resp.status_code == 200
            assert resp.get_json()['html'] == "Hello Test"

    def test_logs_endpoint_success(self, client, auth_headers):
        with patch('mercury.web.routes.api.logs_stats.LogRepository') as MockRepo:
            MockRepo.return_value.get_recent_success.return_value = []
            resp = client.get('/api/logs/success', headers=auth_headers)
            assert resp.status_code == 200

    def test_delete_webhook(self, client, auth_headers):
        with patch('mercury.web.routes.api.webhooks.WebhookService') as MockService:
            resp = client.delete('/api/webhooks/webhook_123', headers=auth_headers)
            assert resp.status_code == 200
            assert resp.get_json()['success'] is True
