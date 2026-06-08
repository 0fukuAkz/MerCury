"""Webhook registration API routes."""

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    WebhookService,
    WebhookEvent,
)


@api_bp.route("/webhooks", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_webhooks():
    """List registered webhooks."""
    service = WebhookService()
    webhooks = service.get_webhooks()

    return jsonify({"webhooks": [w.to_dict() for w in webhooks]})


@api_bp.route("/webhooks", methods=["POST"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_register_webhook():
    """Register new webhook."""
    data = request.get_json(silent=True) or {}

    if not data.get("url"):
        return jsonify({"error": "Webhook URL required"}), 400

    service = WebhookService()

    # Parse events
    events = None
    if data.get("events"):
        events = []
        for e in data["events"]:
            try:
                events.append(WebhookEvent(e))
            except ValueError:
                pass

    webhook = service.register_webhook(
        url=data["url"],
        events=events,
        secret=data.get("secret"),
    )

    return jsonify({"success": True, "webhook": webhook.to_dict()})


@api_bp.route("/webhooks/<webhook_id>", methods=["DELETE"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_webhook(webhook_id):
    """Delete a registered webhook."""
    service = WebhookService()
    service.unregister_webhook(webhook_id)
    return jsonify({"success": True})
