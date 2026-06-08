"""Webhook notification service for external integrations."""

import os
import asyncio
import logging
import json
import hmac
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class WebhookEvent(str, Enum):
    """Webhook event types."""

    # Email events
    EMAIL_SENT = "email.sent"
    EMAIL_DELIVERED = "email.delivered"
    EMAIL_FAILED = "email.failed"
    EMAIL_BOUNCED = "email.bounced"
    EMAIL_OPENED = "email.opened"
    EMAIL_CLICKED = "email.clicked"
    EMAIL_UNSUBSCRIBED = "email.unsubscribed"
    EMAIL_COMPLAINED = "email.complained"

    # Campaign events
    CAMPAIGN_STARTED = "campaign.started"
    CAMPAIGN_PAUSED = "campaign.paused"
    CAMPAIGN_RESUMED = "campaign.resumed"
    CAMPAIGN_COMPLETED = "campaign.completed"
    CAMPAIGN_FAILED = "campaign.failed"

    # System events
    RATE_LIMIT_HIT = "system.rate_limit"
    CIRCUIT_BREAKER_OPENED = "system.circuit_breaker_opened"
    CIRCUIT_BREAKER_CLOSED = "system.circuit_breaker_closed"


@dataclass
class WebhookConfig:
    """Webhook endpoint configuration."""

    id: str
    url: str
    events: List[WebhookEvent] = field(default_factory=list)
    secret: Optional[str] = None
    enabled: bool = True
    retry_count: int = 3
    timeout: float = 10.0
    headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "events": [e.value for e in self.events],
            "enabled": self.enabled,
            "retry_count": self.retry_count,
            "timeout": self.timeout,
        }


@dataclass
class WebhookDelivery:
    """Record of a webhook delivery attempt."""

    id: str
    webhook_id: str
    event: WebhookEvent
    payload: Dict[str, Any]
    timestamp: datetime
    status_code: Optional[int] = None
    response: Optional[str] = None
    success: bool = False
    attempts: int = 0
    error: Optional[str] = None


class WebhookService:
    """
    Service for sending webhook notifications to external systems.

    Features:
    - Multiple webhook endpoints
    - Event filtering per endpoint
    - HMAC signature for security
    - Retry with exponential backoff
    - Async delivery
    """

    def __init__(self):
        """Initialize webhook service."""
        self._webhooks: Dict[str, WebhookConfig] = {}
        self._deliveries: List[WebhookDelivery] = []
        self._client: Optional[httpx.AsyncClient] = None

        # Load webhooks from environment
        self._load_webhooks_from_env()

    def _is_safe_webhook_url(self, url: str) -> bool:
        """Check if webhook URL is safe from SSRF."""
        if os.environ.get("ALLOW_INTERNAL_WEBHOOKS", "False").lower() in ("true", "1", "yes"):
            return True

        try:
            from urllib.parse import urlparse
            import ipaddress
            import socket

            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False

            if hostname.lower() in ("localhost", "metadata.google.internal"):
                return False

            try:
                # Resolve DNS to catch DNS rebinding to local IPs
                resolved_ip = socket.gethostbyname(hostname)
                ip = ipaddress.ip_address(resolved_ip)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
            except (ValueError, socket.gaierror):
                pass  # Could not resolve or invalid IP

            return True
        except Exception:
            return False

    def _load_webhooks_from_env(self) -> None:
        """Load webhook configurations from environment variables."""
        # Format: WEBHOOK_1_URL, WEBHOOK_1_SECRET, WEBHOOK_1_EVENTS
        i = 1
        while True:
            url = os.environ.get(f"WEBHOOK_{i}_URL")
            if not url:
                break

            if not self._is_safe_webhook_url(url):
                logger.warning(
                    f"Skipping webhook env_{i} due to unsafe URL (SSRF protection): {url}"
                )
                i += 1
                continue

            secret = os.environ.get(f"WEBHOOK_{i}_SECRET")
            events_str = os.environ.get(f"WEBHOOK_{i}_EVENTS", "*")

            # Parse events
            if events_str == "*":
                events = list(WebhookEvent)
            else:
                events = []
                for e in events_str.split(","):
                    try:
                        events.append(WebhookEvent(e.strip()))
                    except ValueError:
                        logger.warning(f"Unknown webhook event: {e}")

            webhook = WebhookConfig(id=f"env_{i}", url=url, secret=secret, events=events)

            self._webhooks[webhook.id] = webhook
            logger.info(f"Loaded webhook from environment: {url}")

            i += 1

    def register_webhook(
        self,
        url: str,
        events: Optional[List[WebhookEvent]] = None,
        secret: Optional[str] = None,
        webhook_id: Optional[str] = None,
    ) -> WebhookConfig:
        """
        Register a new webhook endpoint.

        Args:
            url: Webhook endpoint URL
            events: List of events to subscribe to (all if None)
            secret: HMAC secret for signature
            webhook_id: Optional custom ID

        Returns:
            Created WebhookConfig
        """
        import uuid

        if not self._is_safe_webhook_url(url):
            raise ValueError(
                "Webhook URL is not permitted (SSRF protection). Set ALLOW_INTERNAL_WEBHOOKS=True if internal IPs are required."
            )

        webhook = WebhookConfig(
            id=webhook_id or str(uuid.uuid4()),
            url=url,
            events=events or list(WebhookEvent),
            secret=secret,
        )

        self._webhooks[webhook.id] = webhook
        logger.info(f"Registered webhook: {webhook.id} -> {url}")

        return webhook

    def unregister_webhook(self, webhook_id: str) -> bool:
        """Unregister a webhook endpoint."""
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            logger.info(f"Unregistered webhook: {webhook_id}")
            return True
        return False

    def _generate_signature(self, payload: str, secret: str) -> str:
        """
        Generate HMAC signature for webhook payload.

        Args:
            payload: JSON payload string
            secret: Webhook secret

        Returns:
            HMAC-SHA256 signature
        """
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

        return f"sha256={signature}"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True)
        return self._client

    async def _deliver_webhook(
        self, webhook: WebhookConfig, event: WebhookEvent, data: Dict[str, Any]
    ) -> WebhookDelivery:
        """
        Deliver webhook to endpoint.

        Args:
            webhook: Webhook configuration
            event: Event type
            data: Event data

        Returns:
            WebhookDelivery record
        """
        import uuid

        delivery = WebhookDelivery(
            id=str(uuid.uuid4()),
            webhook_id=webhook.id,
            event=event,
            payload=data,
            timestamp=datetime.now(UTC),
        )

        payload = {"event": event.value, "timestamp": datetime.now(UTC).isoformat(), "data": data}

        payload_json = json.dumps(payload, default=str)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event.value,
            "X-Webhook-Timestamp": payload["timestamp"],
            **webhook.headers,
        }

        # Add signature if secret is configured
        if webhook.secret:
            headers["X-Webhook-Signature"] = self._generate_signature(payload_json, webhook.secret)

        client = await self._get_client()

        # Retry loop
        for attempt in range(webhook.retry_count):
            delivery.attempts = attempt + 1

            try:
                response = await client.post(
                    webhook.url, content=payload_json, headers=headers, timeout=webhook.timeout
                )

                delivery.status_code = response.status_code
                delivery.response = response.text[:1000]  # Truncate response

                if 200 <= response.status_code < 300:
                    delivery.success = True
                    logger.debug(f"Webhook delivered: {event.value} -> {webhook.url}")
                    break
                else:
                    logger.warning(
                        f"Webhook failed with status {response.status_code}: {webhook.url}"
                    )

            except Exception as e:
                delivery.error = str(e)
                logger.warning(f"Webhook delivery error: {e}")

            # Exponential backoff
            if attempt < webhook.retry_count - 1:
                await asyncio.sleep(2**attempt)

        self._deliveries.append(delivery)
        # Cap deliveries to prevent memory leak
        if len(self._deliveries) > 1000:
            self._deliveries = self._deliveries[-1000:]

        if not delivery.success:
            logger.error(
                f"Webhook delivery failed after {delivery.attempts} attempts: {webhook.url}"
            )

        return delivery

    async def notify(self, event: WebhookEvent, data: Dict[str, Any]) -> List[WebhookDelivery]:
        """
        Send webhook notification for an event.

        Args:
            event: Event type
            data: Event data

        Returns:
            List of delivery records
        """
        # Find webhooks subscribed to this event
        webhooks = [
            w for w in self._webhooks.values() if w.enabled and (not w.events or event in w.events)
        ]

        if not webhooks:
            return []

        # Deliver to all matching webhooks
        tasks = [self._deliver_webhook(webhook, event, data) for webhook in webhooks]

        deliveries = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        results = []
        for d in deliveries:
            if isinstance(d, WebhookDelivery):
                results.append(d)
            elif isinstance(d, Exception):
                logger.error(f"Webhook delivery exception: {d}")

        return results

    # Convenience methods for common events

    async def notify_email_sent(
        self, recipient: str, subject: str, correlation_id: str, smtp_server: Optional[str] = None
    ) -> List[WebhookDelivery]:
        """Notify that email was sent."""
        return await self.notify(
            WebhookEvent.EMAIL_SENT,
            {
                "recipient": recipient,
                "subject": subject,
                "correlation_id": correlation_id,
                "smtp_server": smtp_server,
            },
        )

    async def notify_email_failed(
        self,
        recipient: str,
        error: str,
        error_type: str,
        correlation_id: str,
        is_transient: bool = False,
    ) -> List[WebhookDelivery]:
        """Notify that email failed."""
        return await self.notify(
            WebhookEvent.EMAIL_FAILED,
            {
                "recipient": recipient,
                "error": error,
                "error_type": error_type,
                "correlation_id": correlation_id,
                "is_transient": is_transient,
            },
        )

    async def notify_email_bounced(
        self, recipient: str, bounce_type: str, category: str, reason: str
    ) -> List[WebhookDelivery]:
        """Notify that email bounced."""
        return await self.notify(
            WebhookEvent.EMAIL_BOUNCED,
            {
                "recipient": recipient,
                "bounce_type": bounce_type,
                "category": category,
                "reason": reason,
            },
        )

    async def notify_campaign_started(
        self, campaign_id: str, campaign_name: str, total_recipients: int
    ) -> List[WebhookDelivery]:
        """Notify that campaign started."""
        return await self.notify(
            WebhookEvent.CAMPAIGN_STARTED,
            {
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "total_recipients": total_recipients,
            },
        )

    async def notify_campaign_completed(
        self,
        campaign_id: str,
        campaign_name: str,
        total: int,
        success: int,
        failed: int,
        duration_seconds: float,
    ) -> List[WebhookDelivery]:
        """Notify that campaign completed."""
        return await self.notify(
            WebhookEvent.CAMPAIGN_COMPLETED,
            {
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
                "total": total,
                "success": success,
                "failed": failed,
                "success_rate": round(success / total * 100, 2) if total > 0 else 0,
                "duration_seconds": round(duration_seconds, 2),
            },
        )

    def get_webhooks(self) -> List[WebhookConfig]:
        """Get all registered webhooks."""
        return list(self._webhooks.values())

    def get_delivery_stats(self) -> Dict[str, Any]:
        """Get webhook delivery statistics."""
        total = len(self._deliveries)
        successful = sum(1 for d in self._deliveries if d.success)

        return {
            "total_deliveries": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": round(successful / total * 100, 2) if total > 0 else 0,
            "by_event": {
                event.value: len([d for d in self._deliveries if d.event == event])
                for event in WebhookEvent
            },
        }

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
