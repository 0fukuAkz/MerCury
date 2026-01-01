"""UI View routes."""

from flask import Blueprint, render_template
from flask_login import login_required

views_bp = Blueprint('views', __name__)

@views_bp.route('/')
@login_required
def index():
    """Main dashboard page."""
    return render_template('index.html')

@views_bp.route('/campaigns')
@login_required
def campaigns():
    """Campaigns list page."""
    return render_template('campaigns.html')

@views_bp.route('/campaigns/new')
@login_required
def new_campaign():
    """New campaign creation form."""
    return render_template('campaign_form.html')

@views_bp.route('/smtp')
@login_required
def smtp_servers():
    """SMTP servers management page."""
    return render_template('smtp.html')

@views_bp.route('/templates')
@login_required
def templates():
    """Email templates management page."""
    return render_template('templates.html')

@views_bp.route('/logs')
@login_required
def logs():
    """System logs viewer."""
    return render_template('logs.html')

@views_bp.route('/recipients')
@login_required
def recipients():
    """Recipients management page."""
    return render_template('recipients.html')


