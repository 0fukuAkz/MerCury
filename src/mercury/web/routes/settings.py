"""Global Settings routes."""

import logging
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from ...services.settings_service import SettingsService

settings_bp = Blueprint('settings', __name__, url_prefix='/settings')
logger = logging.getLogger(__name__)

@settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    """Global settings dashboard."""
    settings = SettingsService.get_settings()
    
    if request.method == 'POST':
        try:
            # Parse form data
            data = {
                'daily_limit': int(request.form.get('daily_limit', 0)),
                'hourly_limit': int(request.form.get('hourly_limit', 0)),
                'min_delay': float(request.form.get('min_delay', 1.0)),
                'max_delay': float(request.form.get('max_delay', 2.0)),
                'default_reply_to': request.form.get('default_reply_to', ''),
                
                # Advanced
                'max_retries': int(request.form.get('max_retries', 3)),
                'retry_delay_base': int(request.form.get('retry_delay_base', 300)),
                'smtp_timeout': int(request.form.get('smtp_timeout', 30)),
                'max_concurrency': int(request.form.get('max_concurrency', 5)),
                'dns_timeout': int(request.form.get('dns_timeout', 5)),
                'proxy_enabled': request.form.get('proxy_enabled') == 'on',
                'proxy_list': request.form.get('proxy_list', '').splitlines(),
                
                # Defaults
                'batch_size': int(request.form.get('batch_size', 1000)),
                'default_sender_name': request.form.get('default_sender_name', ''),
                'default_test_email': request.form.get('default_test_email', ''),
                
                # Logging & UI
                'log_retention_days': int(request.form.get('log_retention_days', 30)),
                'log_level': request.form.get('log_level', 'INFO'),
                'ui_theme': request.form.get('ui_theme', 'dark'),
            }
            
            SettingsService.update_settings(data)
            flash('Settings updated successfully.', 'success')
            return redirect(url_for('settings.index'))
            
        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'error')
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            flash('Failed to update settings.', 'error')

    # Convert proxy list to string for text area
    proxy_text = ""
    if settings.proxy_list:
        proxy_text = "\n".join(settings.proxy_list)

    return render_template(
        'settings.html', 
        settings=settings,
        proxy_text=proxy_text
    )
