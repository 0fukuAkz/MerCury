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

    # Reject non-image logo picks (mirrors the gate on /api/campaigns).
    _logo_raw = data.get('logo_attachment_id')
    if str(_logo_raw or '').strip().isdigit():
        from ....data.repositories import AttachmentRepository as _AR
        from ....data.database import session_scope as _ss
        with _ss() as _session:
            _logo_row = _AR(_session).get(int(_logo_raw))
            if _logo_row is None or not _logo_row.is_active:
                return jsonify({
                    'success': False,
                    'error': f'logo_attachment_id={_logo_raw} not found in library',
                }), 400
            if not (_logo_row.content_type or '').lower().startswith('image/'):
                return jsonify({
                    'success': False,
                    'error': (
                        f"Logo must be an image file (got content_type="
                        f"{_logo_row.content_type!r}). Upload an image to the "
                        f"Attachments library and pick it from the dropdown."
                    ),
                }), 400

    subject = data.get('subject') or '(Test) No subject'
    from_email = data.get('from_email') or ''
    if not from_email:
        return jsonify({'success': False, 'error': 'From Email is required'}), 400

    try:
        # Honor a pinned smtp_server_id if the campaign form specified one.
        # Without this, the test send loads all enabled servers and rotates,
        # which contradicts the user's explicit "Send via" choice.
        pinned_smtp_id: int | None = None
        _raw_pin = data.get('smtp_server_id')
        if _raw_pin not in (None, '', 0, '0'):
            try:
                pinned_smtp_id = int(_raw_pin)
            except (TypeError, ValueError):
                pinned_smtp_id = None

        with session_scope() as session:
            smtp_repo = SMTPRepository(session)
            if pinned_smtp_id is not None:
                one = smtp_repo.get(pinned_smtp_id)
                smtp_servers = [one] if (one and one.is_enabled) else []
                if not smtp_servers:
                    return jsonify({
                        'success': False,
                        'error': f'Pinned SMTP server id={pinned_smtp_id} is missing or disabled',
                    }), 400
            else:
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
        enable_qr_code = data.get('enable_qr_code') in (True, 'on', '1', 'true')
        send_as_image = data.get('send_as_image') in (True, 'on', '1', 'true')

        # Pull attachment fields off the test payload so the test send honors
        # what's set on the form (legacy single-path + library multi-select).
        # Without this, send_single() materializes with empty attachments.
        attachment_ids = [
            int(x) for x in (data.get('attachment_ids') or [])
            if str(x).strip().isdigit()
        ]

        config = EmailConfig(
            subject=subject,
            from_email=from_email,
            from_name=data.get('from_name', ''),
            reply_to=data.get('reply_to') or None,
            placeholders_path=data.get('placeholders_path') or None,
            enable_tracking=enable_tracking,
            track_opens=track_opens,
            track_clicks=track_clicks,
            enable_qr_code=enable_qr_code,
            send_as_image=send_as_image,
            attachment_ids=attachment_ids,
            convert_attachment=bool(data.get('convert_attachment', False)),
            attachment_convert_to=(data.get('attachment_convert_to') or None),
            logo_attachment_id=(
                int(data['logo_attachment_id'])
                if str(data.get('logo_attachment_id') or '').strip().isdigit()
                else None
            ),
            auto_company_logo=data.get('auto_company_logo') in (True, 'on', '1', 'true'),
            hide_from_email_header=data.get('hide_from_email_header') in (True, 'on', '1', 'true'),
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

        # Surface the resolved attachment configuration in the response so
        # the operator can confirm (in DevTools → Network) which path won —
        # library vs legacy — without having to fish through server logs.
        diagnostics = {
            'attachment_ids': attachment_ids,
            'resolved_path': 'library' if attachment_ids else 'none',
            'smtp_server_id': pinned_smtp_id,
            'smtp_servers_loaded': [c.get('name') for c in smtp_configs],
        }
        if result.success:
            return jsonify({
                'success': True,
                'correlation_id': result.correlation_id,
                'diagnostics': diagnostics,
            })
        else:
            return jsonify({
                'success': False,
                'error': result.error or 'Send failed',
                'diagnostics': diagnostics,
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
