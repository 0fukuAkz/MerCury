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
    from ....services.email import EmailService, EmailConfig

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
            # Prevent Arbitrary File Read (C-2)
            try:
                target_path = os.path.realpath(template_path)
                safe_base = os.path.realpath(os.getcwd())
                if target_path.startswith(safe_base) and os.path.isfile(target_path):
                    with open(target_path, 'r', encoding='utf-8') as f:
                        html_body = f.read()
            except Exception:
                pass

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

        # Attachments arrive via the library multi-select (attachment_ids).
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
            include_default_body=data.get('include_default_body') in (True, 'on', '1', 'true'),
        )

        smtp_service = SMTPService()
        smtp_service.load_from_config(smtp_configs)

        # From-ownership preflight: when at least one loaded server has a
        # from_email configured, verify the form's From has an owner. This
        # turns the gateway-side 5.7.0 "From is not one of your addresses"
        # — which is intermittent and confusing — into an actionable error
        # before we open the SMTP connection.
        #
        # Enforcement only kicks in when at least one server declares
        # ownership; otherwise From-routing isn't in play.
        servers_with_from = [c for c in smtp_configs if (c.get('from_email') or '').strip()]
        pool = smtp_service.get_connection_pool() if servers_with_from else None
        owning_server_name: str | None = None
        if pool is not None:
            owner = pool.select_server_for_from(from_email)
            owning_server_name = owner.name if owner else None
            if owner is None:
                authorized = [c.get('from_email') for c in servers_with_from]
                return jsonify({
                    'success': False,
                    'error': (
                        f"From '{from_email}' is not authorized on any configured SMTP "
                        f"server. Configured senders: {authorized}. Either change the "
                        f"From, or set 'From Email' on the SMTP server that should "
                        f"send as this address."
                    ),
                    'diagnostics': {
                        'from_email': from_email,
                        'authorized_from_emails': authorized,
                        'smtp_servers_loaded': [c.get('name') for c in smtp_configs],
                    },
                }), 400

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
        # the operator can confirm (in DevTools → Network) what got materialized
        # without having to fish through server logs.
        diagnostics = {
            'attachment_ids': attachment_ids,
            'resolved_path': 'library' if attachment_ids else 'none',
            'smtp_server_id': pinned_smtp_id,
            'smtp_servers_loaded': [c.get('name') for c in smtp_configs],
            # 'from_email_used' is what actually went on the wire — operators
            # can compare against the form input to spot {{placeholder}}
            # substitution mishaps. 'routed_via' + 'owner_match' say which
            # server the engine picked and whether From-ownership matched.
            'from_email_used': from_email,
            'routed_via': result.smtp_server,
            'owner_match': (
                'yes' if owning_server_name and owning_server_name == result.smtp_server
                else ('no_servers_declare_from' if not servers_with_from else 'fallback')
            ),
            # Per-send placeholder diagnostics from EmailService. Tells the
            # operator (for example) that {{qr_code}} is referenced in the
            # body but resolved empty because 'Enable QR code' was off OR
            # no primary link was set.
            **getattr(service, 'last_send_diagnostics', {}),
        }
        # If QR was referenced but didn't resolve, surface as a top-level
        # warning so the UI can highlight it even on a "success" send.
        if diagnostics.get('qr_code_referenced_in_body') and not diagnostics.get('qr_code_resolved'):
            diagnostics['warnings'] = diagnostics.get('warnings', []) + [
                f"{{{{qr_code}}}} is referenced in the body but the QR could not be generated "
                f"(enable_qr_code={diagnostics.get('enable_qr_code')}, link_present="
                f"{diagnostics.get('link_present')}). Enable the QR toggle AND set a primary link."
            ]
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
