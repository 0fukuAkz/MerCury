"""Dead-letter queue API routes."""

import logging

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    run_async,
    session_scope,
)
from ....data.repositories.dead_letter import DeadLetterRepository
from ....services.dead_letter_service import DeadLetterService

logger = logging.getLogger(__name__)


@api_bp.route("/dead-letter", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_dead_letters():
    """List dead letter queue items."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        items = service.get_unresolved(limit=100)
        return jsonify(
            {
                "items": [item.to_dict() for item in items],
                "count": len(items),
            }
        )


@api_bp.route("/dead-letter/<int:item_id>/retry", methods=["POST"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_retry_dead_letter(item_id):
    """Increment the retry counter for a dead letter item (log-only, no send)."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        result = service.retry_dead_letter(item_id)
        return jsonify({"success": result is not None})


def _requeue_item(item_id: int, pinned_smtp_id=None):
    """Internal helper: re-send a dead letter item via SMTP.

    Returns a dict with keys: success, smtp_server, smtp_response, error.
    Increments retry_count on failure; marks resolved on success.
    Separated from the route so requeue-all can call it without going
    through HTTP.
    """
    # Load the dead letter payload.
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        item = repo.get(item_id)
        if not item:
            return {"success": False, "error": f"Dead letter id={item_id} not found"}
        if item.resolved:
            return {"success": False, "error": "Item is already resolved"}
        # Snapshot before session closes.
        recipient = item.recipient
        subject = item.subject
        html_body = item.html_body
        from_email = item.from_email or ""
        from_name = item.from_name or ""

    # Load SMTP servers.
    from ....data.repositories.smtp import SMTPRepository
    from ....services.smtp_service import SMTPService
    from ....services.email.config import EmailConfig
    from ....services.email.service import EmailService

    with session_scope() as session:
        smtp_repo = SMTPRepository(session)
        if pinned_smtp_id is not None:
            one = smtp_repo.get(pinned_smtp_id)
            smtp_servers = [one] if (one and one.is_enabled) else []
            if not smtp_servers:
                return {
                    "success": False,
                    "error": f"Pinned SMTP server id={pinned_smtp_id} is missing or disabled",
                }
        else:
            smtp_servers = smtp_repo.get_all()
        smtp_configs = [s.get_connection_config() for s in smtp_servers if s.is_enabled]

    if not smtp_configs:
        return {"success": False, "error": "No active SMTP servers configured"}

    # Auto-fill from_email / from_name from SMTP server when missing.
    if not from_email:
        from_email = (smtp_configs[0].get("from_email") or "").strip()
    if not from_name:
        from_name = (smtp_configs[0].get("from_name") or "").strip()

    if not from_email:
        return {
            "success": False,
            "error": (
                "Dead letter has no from_email and no SMTP server default is configured. "
                'Set a "From Email" on an SMTP server and retry.'
            ),
        }

    config = EmailConfig(subject=subject, from_email=from_email, from_name=from_name)
    smtp_service = SMTPService()
    smtp_service.load_from_config(smtp_configs)
    service = EmailService(smtp_service)
    service.configure(config)

    result = run_async(
        service.send_single(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=from_email,
            from_name=from_name,
        )
    )

    if result.success:
        with session_scope() as session:
            repo2 = DeadLetterRepository(session)
            svc2 = DeadLetterService(repo2)
            svc2.mark_resolved(
                item_id, f"Requeued and delivered via {result.smtp_server or 'SMTP'}"
            )
            svc2.retry_dead_letter(item_id)
        logger.info("♻️  Dead letter id=%d requeued → %s", item_id, recipient)
        return {
            "success": True,
            "smtp_server": result.smtp_server,
            "smtp_response": result.smtp_response,
        }
    else:
        with session_scope() as session:
            repo2 = DeadLetterRepository(session)
            svc2 = DeadLetterService(repo2)
            svc2.retry_dead_letter(item_id)
        logger.warning("♻️  Dead letter id=%d requeue failed: %s", item_id, result.error)
        return {
            "success": False,
            "error": result.error or "Send failed",
            "smtp_server": result.smtp_server,
        }


@api_bp.route("/dead-letter/<int:item_id>/requeue", methods=["POST"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_requeue_dead_letter(item_id):
    """Re-send a dead letter via SMTP and mark resolved on success.

    Optional JSON body:
        smtp_server_id (int) — pin to a specific server (default: auto)
    """
    data = request.get_json(silent=True) or {}
    pinned_smtp_id = None
    _raw = data.get("smtp_server_id")
    if _raw not in (None, "", 0, "0"):
        try:
            pinned_smtp_id = int(_raw)
        except (TypeError, ValueError):
            pass

    try:
        outcome = _requeue_item(item_id, pinned_smtp_id)
        status = 200
        if not outcome["success"] and "not found" in outcome.get("error", ""):
            status = 404
        return jsonify(outcome), status
    except Exception as e:
        logger.exception("Dead letter requeue error id=%d", item_id)
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route("/dead-letter/requeue-all", methods=["POST"])
@api_key_or_login_required
@limiter.limit("2/minute")
def api_requeue_all_dead_letters():
    """Create a new editable campaign from all unresolved dead letters.

    Instead of sending immediately, this clones the most frequent source
    campaign, adds all dead letter recipients to its manual_recipients list,
    marks the dead letters as resolved, and redirects the user to the
    campaign editor.
    """
    from collections import Counter
    from ....data.models.campaign import Campaign, CampaignStatus
    from ....data.repositories.campaign import CampaignRepository

    with session_scope() as session:
        dl_repo = DeadLetterRepository(session)
        items = dl_repo.get_unresolved(limit=10000)

        if not items:
            return jsonify({"success": False, "error": "No pending messages to requeue"})

        # Find the most common campaign_id among the dead letters
        campaign_ids = [item.campaign_id for item in items if item.campaign_id]
        most_common_campaign_id = None
        if campaign_ids:
            most_common_campaign_id = Counter(campaign_ids).most_common(1)[0][0]

        emails = list(set([item.recipient for item in items if item.recipient]))

        camp_repo = CampaignRepository(session)
        src = camp_repo.get(most_common_campaign_id) if most_common_campaign_id else None

        if src:
            # Clone the source campaign
            clone = Campaign(
                name=src.name + " (Dead Letter Recovery)",
                description="Recovery campaign for failed messages.",
                type=src.type,
                status=CampaignStatus.DRAFT,
                template_id=src.template_id,
                recipient_list_id=src.recipient_list_id,
                from_email=src.from_email,
                from_name=src.from_name,
                reply_to=src.reply_to,
                subjects=list(src.subjects or []),
                subject_rotation_strategy=src.subject_rotation_strategy,
                placeholders=dict(src.placeholders or {}),
                chunk_size=src.chunk_size,
                concurrency=src.concurrency,
                rate_per_minute=src.rate_per_minute,
                rate_per_hour=src.rate_per_hour,
                enable_qr_code=src.enable_qr_code,
                convert_to_image=src.convert_to_image,
                convert_to_pdf=src.convert_to_pdf,
                smtp_rotation_strategy=src.smtp_rotation_strategy,
                auto_failover=src.auto_failover,
                settings=dict(src.settings or {}),
            )
            # Store the list of failed emails in filter_emails setting
            # so the recovery campaign only sends to those who failed.
            clone.settings["filter_emails"] = emails
        else:
            # Create a blank campaign if no source is available
            clone = Campaign(
                name="Dead Letter Recovery",
                description="Recovery campaign for failed messages.",
                status=CampaignStatus.DRAFT,
            )
            clone.settings = {"manual_recipients": emails}

        clone = camp_repo.create(clone)
        new_campaign_id = clone.id

        # Mark the dead letters as resolved since they've been moved to a new campaign
        dl_service = DeadLetterService(dl_repo)
        dl_service.discard_all_unresolved(f"Requeued to campaign #{new_campaign_id}")

    return jsonify(
        {
            "success": True,
            "redirect_url": f"/campaigns/{new_campaign_id}/edit",
            "message": f"Created recovery campaign with {len(emails)} recipients",
        }
    )


@api_bp.route("/dead-letter/<int:item_id>", methods=["DELETE"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_discard_dead_letter(item_id):
    """Discard a dead letter item (mark as resolved)."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        result = service.mark_resolved(item_id, "Discarded via UI")
        return jsonify({"success": result is not None})


@api_bp.route("/dead-letter/discard-all", methods=["POST"])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_discard_all_dead_letters():
    """Bulk-discard every unresolved dead letter (mark all as resolved)."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        count = service.discard_all_unresolved("Bulk-discarded via UI")
        return jsonify({"success": True, "discarded": count})


@api_bp.route("/dead-letter/stats", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_dead_letter_stats():
    """Get dead letter queue statistics."""
    with session_scope() as session:
        repo = DeadLetterRepository(session)
        service = DeadLetterService(repo)
        stats = service.get_statistics()
        return jsonify(stats)
