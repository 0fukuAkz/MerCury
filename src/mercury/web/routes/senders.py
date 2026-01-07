"""Sender Identity routes."""

import logging
from flask import Blueprint, render_template, request, flash, redirect, url_for
from ...services.identity_service import IdentityService

senders_bp = Blueprint('senders', __name__, url_prefix='/senders')
logger = logging.getLogger(__name__)

@senders_bp.route('/')
def index():
    """Sender identities dashboard."""
    emails = IdentityService.get_emails()
    names = IdentityService.get_names()
    return render_template('senders.html', emails=emails, names=names)

@senders_bp.route('/emails', methods=['POST'])
def add_email():
    """Add a new From-Email."""
    email = request.form.get('email', '').strip()
    tags = request.form.get('tags', '').split(',')
    tags = [t.strip() for t in tags if t.strip()]
    
    if not email:
        flash('Email is required.', 'error')
    else:
        try:
            IdentityService.add_email(email, tags)
            flash('Email added successfully.', 'success')
        except Exception as e:
            logger.error(f"Error adding email: {e}")
            flash('Failed to add email.', 'error')
            
    return redirect(url_for('senders.index'))

@senders_bp.route('/emails/<int:id>/toggle', methods=['POST'])
def toggle_email(id):
    """Toggle status."""
    IdentityService.toggle_email_status(id)
    return redirect(url_for('senders.index'))

@senders_bp.route('/emails/<int:id>/delete', methods=['POST'])
def delete_email(id):
    """Delete email."""
    IdentityService.delete_email(id)
    flash('Email deleted.', 'success')
    return redirect(url_for('senders.index'))

@senders_bp.route('/names', methods=['POST'])
def add_name():
    """Add a new Sender Name."""
    name = request.form.get('name', '').strip()
    tags = request.form.get('tags', '').split(',')
    tags = [t.strip() for t in tags if t.strip()]
    
    if not name:
        flash('Name is required.', 'error')
    else:
        try:
            IdentityService.add_name(name, tags)
            flash('Name added successfully.', 'success')
        except Exception as e:
            logger.error(f"Error adding name: {e}")
            flash('Failed to add name.', 'error')
            
    return redirect(url_for('senders.index'))

@senders_bp.route('/names/<int:id>/toggle', methods=['POST'])
def toggle_name(id):
    """Toggle status."""
    IdentityService.toggle_name_status(id)
    return redirect(url_for('senders.index'))

@senders_bp.route('/names/<int:id>/delete', methods=['POST'])
def delete_name(id):
    """Delete name."""
    IdentityService.delete_name(id)
    flash('Name deleted.', 'success')
    return redirect(url_for('senders.index'))
