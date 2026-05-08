"""Campaign test-send API route.

Split out of campaigns.py: test-email is a one-shot synchronous send that
shares no state with CRUD or lifecycle, has its own SMTP/template loading
shape, and was the largest single handler in the file.
"""

import os

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    run_async,
    session_scope,
    SMTPRepository,
    TemplateRepository,
    SMTPService,
)


@api_bp.route('/campaigns/test-email', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_send_test_email():
    """Send a single test email using the provided campaign settings."""
    from ....services.email_service import EmailService, EmailConfig

    data = request.get_json(silent=True) or {}
    recipient = (data.get('test_recipient') or '').strip().lower()
    if not recipient or '@' not in recipient:
        return jsonify({'success': False, 'error': 'Valid test_recipient is required'}), 400

    subject = data.get('subject') or '(Test) No subject'
    from_email = data.get('from_email') or ''
    if not from_email:
        return jsonify({'success': False, 'error': 'From Email is required'}), 400

    try:
        with session_scope() as session:
            smtp_repo = SMTPRepository(session)
            smtp_servers = smtp_repo.get_all()
            smtp_configs = [s.get_connection_config() for s in smtp_servers if s.is_enabled]
            if not smtp_configs:
                return jsonify({'success': False, 'error': 'No active SMTP servers configured'}), 400

        template_id = data.get('template_id')
        template_path = data.get('template_path')
        html_body = None
        if template_id:
            with session_scope() as session:
                trepo = TemplateRepository(session)
                tpl = trepo.get(int(template_id))
                if tpl:
                    html_body = tpl.html_content
        elif template_path:
            if os.path.isfile(template_path):
                with open(template_path, 'r', encoding='utf-8') as f:
                    html_body = f.read()

        primary_link = (data.get('primary_link') or '').strip()
        links_raw = data.get('links') or data.get('links_list') or []
        if isinstance(links_raw, str):
            links_raw = [line.strip() for line in links_raw.splitlines() if line.strip()]
        link_to_use = primary_link or (links_raw[0] if links_raw else None)

        # Checkboxes arrive as "on" / absent; normalize to bool.
        enable_tracking = data.get('enable_tracking') in (True, 'on', '1', 'true')
        track_opens = data.get('track_opens') in (True, 'on', '1', 'true')
        track_clicks = data.get('track_clicks') in (True, 'on', '1', 'true')

        config = EmailConfig(
            subject=subject,
            from_email=from_email,
            from_name=data.get('from_name', ''),
            reply_to=data.get('reply_to') or None,
            placeholders_path=data.get('placeholders_path') or None,
            enable_tracking=enable_tracking,
            track_opens=track_opens,
            track_clicks=track_clicks,
        )

        smtp_service = SMTPService()
        smtp_service.load_from_config(smtp_configs)

        service = EmailService(smtp_service)
        service.configure(config)
        result = run_async(service.send_single(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=from_email,
            from_name=data.get('from_name', ''),
            reply_to=data.get('reply_to') or None,
            link=link_to_use,
        ))

        if result.success:
            return jsonify({'success': True, 'correlation_id': result.correlation_id})
        else:
            return jsonify({'success': False, 'error': result.error or 'Send failed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
