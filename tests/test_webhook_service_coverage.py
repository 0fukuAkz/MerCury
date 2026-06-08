"""Tests for webhook_service.py coverage."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from mercury.services.webhook_service import WebhookService, WebhookEvent, WebhookConfig


@pytest.fixture
async def webhook_service():
    service = WebhookService()
    yield service
    await service.close()


def test_webhook_config_to_dict():
    config = WebhookConfig(id="1", url="http://test.com", events=[WebhookEvent.EMAIL_SENT])
    d = config.to_dict()
    assert d["url"] == "http://test.com"
    assert d["events"] == ["email.sent"]


def test_webhook_load_from_env(monkeypatch):
    monkeypatch.setenv("WEBHOOK_1_URL", "http://env1.com")
    monkeypatch.setenv("WEBHOOK_1_SECRET", "secret1")
    monkeypatch.setenv("WEBHOOK_1_EVENTS", "email.sent,campaign.started")

    service = WebhookService()
    assert "env_1" in service._webhooks
    assert service._webhooks["env_1"].url == "http://env1.com"
    assert WebhookEvent.EMAIL_SENT in service._webhooks["env_1"].events


def test_webhook_registration():
    service = WebhookService()
    config = service.register_webhook(
        "http://reg.com", events=[WebhookEvent.CAMPAIGN_COMPLETED], secret="regsec"
    )
    assert config.url == "http://reg.com"
    assert service.unregister_webhook(config.id) is True
    assert service.unregister_webhook("nonexistent") is False


@pytest.mark.asyncio
async def test_webhook_notify_success(webhook_service):
    # Mock httpx client
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "OK"
    mock_client.post.return_value = mock_response

    webhook_service._client = mock_client
    webhook_service.register_webhook("http://success.com", secret="sec")

    deliveries = await webhook_service.notify(WebhookEvent.EMAIL_SENT, {"id": "123"})
    assert len(deliveries) == 1
    assert deliveries[0].success is True
    assert deliveries[0].status_code == 200


@pytest.mark.asyncio
async def test_webhook_notify_retry_failure(webhook_service):
    mock_client = AsyncMock()
    mock_client.post.side_effect = Exception("Connection Error")

    webhook_service._client = mock_client
    webhook_service.register_webhook("http://fail.com")

    # Patch sleep to avoid waiting
    with patch("asyncio.sleep", return_value=None):
        deliveries = await webhook_service.notify(WebhookEvent.EMAIL_SENT, {"id": "123"})

    assert len(deliveries) == 1
    assert deliveries[0].success is False
    assert deliveries[0].attempts == 3  # Default retry count


def test_webhook_get_stats(webhook_service):
    from mercury.services.webhook_service import WebhookDelivery
    from datetime import datetime

    delivery = WebhookDelivery(
        id="d1",
        webhook_id="w1",
        event=WebhookEvent.EMAIL_SENT,
        payload={},
        timestamp=datetime.now(),
        success=True,
    )
    webhook_service._deliveries.append(delivery)

    stats = webhook_service.get_delivery_stats()
    assert stats["total_deliveries"] == 1
    assert stats["success_rate"] == 100.0


@pytest.mark.asyncio
async def test_webhook_convenience_methods(webhook_service):
    webhook_service.notify = AsyncMock(return_value=[])

    await webhook_service.notify_email_sent("test@exp.com", "Sub", "cor1")
    args, kwargs = webhook_service.notify.call_args
    assert args[0] == WebhookEvent.EMAIL_SENT
    assert args[1]["recipient"] == "test@exp.com"

    await webhook_service.notify_email_failed("test@exp.com", "Err", "Type", "cor2")
    args, kwargs = webhook_service.notify.call_args
    assert args[0] == WebhookEvent.EMAIL_FAILED

    await webhook_service.notify_campaign_started("c1", "Name", 100)
    args, kwargs = webhook_service.notify.call_args
    assert args[0] == WebhookEvent.CAMPAIGN_STARTED

    await webhook_service.notify_campaign_completed("c1", "Name", 100, 90, 10, 60.0)
    args, kwargs = webhook_service.notify.call_args
    assert args[0] == WebhookEvent.CAMPAIGN_COMPLETED
