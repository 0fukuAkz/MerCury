"""Template management routes."""

import logging
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from ...data.database import session_scope
from ...data.repositories import TemplateRepository
from ...data.models import Template

templates_bp = Blueprint('templates', __name__, url_prefix='/templates')
logger = logging.getLogger(__name__)


@templates_bp.route('/')
@login_required
def index():
    """Templates management page."""
    with session_scope() as session:
        repo = TemplateRepository(session)
        templates = repo.get_all()
        return render_template('templates.html', templates=templates)


@templates_bp.route('/save', methods=['POST'])
@login_required
def save():
    """Create or update a template."""
    template_id = request.form.get('template_id', '').strip()
    name = request.form.get('name', '').strip()
    subject = request.form.get('subject', '').strip()
    html_content = request.form.get('html_content', '').strip()

    if not name:
        flash('Template name is required.', 'error')
        return redirect(url_for('templates.index'))

    try:
        with session_scope() as session:
            repo = TemplateRepository(session)

            if template_id:
                # Update existing
                template = repo.get(int(template_id))
                if template:
                    template.name = name
                    template.subject = subject
                    template.html_content = html_content
                    session.commit()
                    flash('Template updated successfully.', 'success')
                else:
                    flash('Template not found.', 'error')
            else:
                # Create new
                template = Template(
                    name=name,
                    subject=subject,
                    html_content=html_content,
                    is_active=True,
                )
                session.add(template)
                session.commit()
                flash('Template created successfully.', 'success')
    except Exception as e:
        # session_scope already rolled back; log and flash for the user.
        logger.error(f"Error saving template: {e}")
        flash('Failed to save template.', 'error')

    return redirect(url_for('templates.index'))


@templates_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    """Delete a template."""
    try:
        with session_scope() as session:
            repo = TemplateRepository(session)
            template = repo.get(id)
            if template:
                if template.campaigns:
                    flash('Cannot delete template linked to campaigns.', 'error')
                else:
                    repo.delete(template)
                    flash('Template deleted.', 'success')
            else:
                flash('Template not found.', 'error')
    except Exception as e:
        logger.error(f"Error deleting template: {e}")
        flash('Failed to delete template.', 'error')

    return redirect(url_for('templates.index'))


@templates_bp.route('/<int:id>/toggle', methods=['POST'])
@login_required
def toggle(id):
    """Toggle template active status."""
    try:
        with session_scope() as session:
            repo = TemplateRepository(session)
            template = repo.get(id)
            if template:
                template.is_active = not template.is_active
                session.commit()
                status = 'activated' if template.is_active else 'deactivated'
                flash(f'Template {status}.', 'success')
            else:
                flash('Template not found.', 'error')
    except Exception as e:
        logger.error(f"Error toggling template: {e}")
        flash('Failed to update template.', 'error')

    return redirect(url_for('templates.index'))
