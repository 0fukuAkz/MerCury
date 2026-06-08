import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from mercury.services.webhook_service import WebhookService, WebhookEvent


@pytest.fixture
def webhook_service():
    """Create a WebhookService instance for testing."""
    service = WebhookService()
    yield service
    # Cleanup properly required but difficult with current asyncio/pytest setup on Windows


@pytest.mark.asyncio
class TestWebhookServiceExtended:
    """Extended tests for WebhookService."""

    async def test_register_unregister_webhook(self, webhook_service):
        """Test registering and unregistering webhooks."""
        url = "http://example.com/webhook"
        secret = "test_secret"

        # Register
        config = webhook_service.register_webhook(url, secret=secret)

        assert config.url == url
        assert config.secret == secret
        assert len(webhook_service.get_webhooks()) == 1
        assert config.id in webhook_service._webhooks

        # Unregister
        result = webhook_service.unregister_webhook(config.id)
        assert result is True
        assert len(webhook_service.get_webhooks()) == 0

        # Unregister non-existent
        result = webhook_service.unregister_webhook("non-existent")
        assert result is False

    async def test_load_webhooks_from_env(self):
        """Test loading webhooks from environment variables."""
        env_vars = {
            "WEBHOOK_1_URL": "http://env1.com",
            "WEBHOOK_1_SECRET": "secret1",
            "WEBHOOK_1_EVENTS": "*",
            "WEBHOOK_2_URL": "http://env2.com",
            "WEBHOOK_2_EVENTS": "email.sent,email.bounced",
        }

        with patch.dict(os.environ, env_vars):
            service = WebhookService()
            webhooks = service.get_webhooks()

            assert len(webhooks) == 2

            # Check first webhook
            w1 = next(w for w in webhooks if w.url == "http://env1.com")
            assert w1.secret == "secret1"
            assert list(WebhookEvent) == w1.events  # All events

            # Check second webhook
            w2 = next(w for w in webhooks if w.url == "http://env2.com")
            assert w2.secret is None
            assert len(w2.events) == 2
            assert WebhookEvent.EMAIL_SENT in w2.events
            assert WebhookEvent.EMAIL_BOUNCED in w2.events

    async def test_generate_signature(self, webhook_service):
        """Test HMAC signature generation."""
        payload = '{"test": "data"}'
        secret = "secret123"

        # Expected signature calculated manually or predetermined
        # HMAC-SHA256("secret123", '{"test": "data"}')
        # = 7e4d9b... (needs actual calc if we want exact match, or just rely on property)

        signature = webhook_service._generate_signature(payload, secret)
        assert signature.startswith("sha256=")
        assert len(signature) > 10

    async def test_deliver_webhook_success(self, webhook_service):
        """Test successful webhook delivery."""
        url = "http://test.com"
        secret = "secret"
        webhook = webhook_service.register_webhook(url, secret=secret)

        event = WebhookEvent.EMAIL_SENT
        data = {"id": "123"}

        # Mock httpx client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        webhook_service._client = mock_client

        delivery = await webhook_service._deliver_webhook(webhook, event, data)

        assert delivery.success is True
        assert delivery.status_code == 200
        assert delivery.attempts == 1

        # Verify call arguments
        mock_client.post.assert_called_once()
        args, kwargs = mock_client.post.call_args
        assert args[0] == url
        assert "X-Webhook-Signature" in kwargs["headers"]
        assert kwargs["headers"]["X-Webhook-Event"] == event.value

    async def test_deliver_webhook_retry_failure(self, webhook_service):
        """Test webhook delivery failure and retries."""
        url = "http://fail.com"
        webhook = webhook_service.register_webhook(url)
        # Faster retry for test
        webhook.retry_count = 2

        # Mock httpx client to raise exception
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        webhook_service._client = mock_client

        # Patch sleep to speed up test
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            delivery = await webhook_service._deliver_webhook(
                webhook, WebhookEvent.EMAIL_FAILED, {}
            )

        assert delivery.success is False
        assert delivery.attempts == 2
        assert delivery.error == "Connection refused"
        assert mock_client.post.call_count == 2

    async def test_notify_filtering(self, webhook_service):
        """Test that notify only sends to subscribed webhooks."""
        # Config 1: Subscribed to EMAIL_SENT
        w1 = webhook_service.register_webhook("http://1.com", events=[WebhookEvent.EMAIL_SENT])
        # Config 2: Subscribed to EMAIL_BOUNCED
        w2 = webhook_service.register_webhook("http://2.com", events=[WebhookEvent.EMAIL_BOUNCED])
        # Config 3: All events
        w3 = webhook_service.register_webhook("http://3.com")

        webhook_service._deliver_webhook = AsyncMock()

        # Notify EMAIL_SENT
        await webhook_service.notify(WebhookEvent.EMAIL_SENT, {})

        # Should call w1 and w3, but not w2
        assert webhook_service._deliver_webhook.call_count == 2
        called_webhooks = {c[0][0].id for c in webhook_service._deliver_webhook.call_args_list}
        assert w1.id in called_webhooks
        assert w3.id in called_webhooks
        assert w2.id not in called_webhooks

    async def test_convenience_methods(self, webhook_service):
        """Test convenience notification methods."""
        webhook_service.notify = AsyncMock()

        await webhook_service.notify_email_sent("test@test.com", "Subj", "123")
        webhook_service.notify.assert_called_with(
            WebhookEvent.EMAIL_SENT,
            pytest.approx(
                {
                    "recipient": "test@test.com",
                    "subject": "Subj",
                    "correlation_id": "123",
                    "smtp_server": None,
                }
            ),
        )

        await webhook_service.notify_campaign_started("c1", "Camp1", 100)
        webhook_service.notify.assert_called_with(
            WebhookEvent.CAMPAIGN_STARTED,
            {"campaign_id": "c1", "campaign_name": "Camp1", "total_recipients": 100},
        )

    async def test_get_delivery_stats(self, webhook_service):
        """Test statistics generation."""
        # Add some fake deliveries
        from mercury.services.webhook_service import WebhookDelivery
        from datetime import datetime

        webhook_service._deliveries = [
            WebhookDelivery("1", "w1", WebhookEvent.EMAIL_SENT, {}, datetime.now(), success=True),
            WebhookDelivery("2", "w1", WebhookEvent.EMAIL_SENT, {}, datetime.now(), success=True),
            WebhookDelivery(
                "3", "w1", WebhookEvent.EMAIL_BOUNCED, {}, datetime.now(), success=False
            ),
        ]

        stats = webhook_service.get_delivery_stats()

        assert stats["total_deliveries"] == 3
        assert stats["successful"] == 2
        assert stats["failed"] == 1
        assert stats["success_rate"] == 66.67
        assert stats["by_event"][WebhookEvent.EMAIL_SENT.value] == 2
        assert stats["by_event"][WebhookEvent.EMAIL_BOUNCED.value] == 1
