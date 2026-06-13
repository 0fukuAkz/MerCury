"""Tests for dead letter API."""

import json
from unittest.mock import patch, MagicMock

from mercury.web.routes.api.dead_letter import _requeue_item


def test_requeue_item_missing_pinned_server():
    with patch("mercury.web.routes.api.dead_letter.session_scope") as mock_scope:
        # First session_scope yields item
        mock_item = MagicMock()
        mock_item.resolved = False
        mock_item.recipient = "test@test.com"
        mock_item.subject = "Subj"
        mock_item.html_body = "body"
        mock_item.from_email = "test@test.com"
        mock_item.from_name = "Test"
        
        # Second session_scope yields empty smtp repo for pinned id
        mock_smtp_repo = MagicMock()
        mock_smtp_repo.get.return_value = None
        
        with patch("mercury.web.routes.api.dead_letter.DeadLetterRepository") as mock_dl_repo, \
             patch("mercury.data.repositories.smtp.SMTPRepository", return_value=mock_smtp_repo):
            mock_dl_repo.return_value.get.return_value = mock_item
            
            result = _requeue_item(1, pinned_smtp_id=99)
            assert result["success"] is False
            assert "missing or disabled" in result["error"]


def test_requeue_dead_letter_invalid_server_id(client, auth_headers):
    with patch("mercury.web.routes.api.dead_letter._requeue_item") as mock_requeue:
        mock_requeue.return_value = {"success": True}
        
        response = client.post(
            "/api/dead-letter/1/requeue",
            json={"smtp_server_id": "invalid_int"},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        # Should fall back to pinned_smtp_id = None
        mock_requeue.assert_called_once_with(1, None)


def test_requeue_dead_letter_exception(client, auth_headers):
    with patch("mercury.web.routes.api.dead_letter._requeue_item") as mock_requeue:
        mock_requeue.side_effect = Exception("Database crashed")
        
        response = client.post(
            "/api/dead-letter/1/requeue",
            json={},
            headers=auth_headers
        )
        
        assert response.status_code == 500
        resp_data = json.loads(response.data)
        assert resp_data["success"] is False
        assert "Database crashed" in resp_data["error"]
