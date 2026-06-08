"""UI View routes."""

from flask import Blueprint, render_template
from flask_login import login_required

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
@login_required
def index():
    """Main dashboard page."""
    return render_template("index.html")


@views_bp.route("/campaigns")
@login_required
def campaigns():
    """Campaigns list page."""
    return render_template("campaigns.html")


@views_bp.route("/campaigns/new")
@login_required
def new_campaign():
    """New campaign creation form."""
    return render_template("campaign_form.html", campaign=None)


@views_bp.route("/campaigns/<int:campaign_id>/edit")
@login_required
def edit_campaign(campaign_id):
    """Edit an existing campaign."""
    from ...data.repositories import CampaignRepository
    from ...data.database import session_scope

    with session_scope() as session:
        repo = CampaignRepository(session)
        campaign = repo.get(campaign_id)
        if not campaign:
            from flask import abort

            abort(404)
        campaign_dict = campaign.to_dict()
    return render_template("campaign_form.html", campaign=campaign_dict)


@views_bp.route("/smtp")
@login_required
def smtp_servers():
    """SMTP servers management page."""
    return render_template("smtp.html")


@views_bp.route("/logs")
@login_required
def logs():
    """System logs viewer."""
    return render_template("logs.html")


@views_bp.route("/recipients")
@login_required
def recipients():
    """Recipients management page."""
    return render_template("recipients.html")


@views_bp.route("/scheduling")
@login_required
def scheduling():
    """Campaign scheduling management page."""
    return render_template("scheduling.html")


@views_bp.route("/bounces")
@login_required
def bounces():
    """Bounce and suppression list management page."""
    return render_template("bounces.html")


@views_bp.route("/dead-letter")
@login_required
def dead_letter():
    """Dead letter queue viewer page."""
    return render_template("dead_letter.html")


@views_bp.route("/webhooks")
@login_required
def webhooks():
    """Webhook management page."""
    return render_template("webhooks.html")


@views_bp.route("/placeholders")
@login_required
def placeholders():
    """Placeholder reference + custom-placeholder admin page."""
    return render_template("placeholders.html")
