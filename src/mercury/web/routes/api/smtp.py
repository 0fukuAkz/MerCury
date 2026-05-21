"""SMTP server management API routes."""

from typing import Any, Optional

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    run_async,
    session_scope,
    SMTPRepository,
    SMTPService,
)


def _validate_smtp_payload(data: dict, *, partial: bool) -> Optional[str]:
    """Cross-field validation that the model itself cannot express.

    ``partial=True`` for PUT (only fields present in ``data`` are checked);
    ``partial=False`` for POST (all required fields must be present and
    coherent). Returns an error string, or None if valid.

    Why these checks are *here* and not in the model: SQLAlchemy column
    constraints can't enforce relationships between columns (e.g.
    "use_auth=True implies username non-empty"). Catching invalid combos
    at the API boundary avoids storing data the engine will trip on later.
    """

    def _is_true(v: Any) -> bool:
        return v in (True, 'true', 'True', 1, '1', 'on')

    # tls_mode is the preferred field — single enum 'none'|'starttls'|'ssl'.
    if 'tls_mode' in data:
        if data['tls_mode'] not in ('none', 'starttls', 'ssl'):
            return "tls_mode must be one of 'none', 'starttls', 'ssl'"

    # Legacy bools: still accepted but the engine derives tls_mode from
    # them at write time. Both True is a no-op contradiction the engine
    # used to silently resolve via OR — reject explicitly.
    if 'use_tls' in data and 'use_ssl' in data:
        if _is_true(data['use_tls']) and _is_true(data['use_ssl']):
            return 'use_tls and use_ssl are mutually exclusive (use tls_mode instead)'

    # use_auth=True with no username silently degrades to anonymous send
    # at connect time, which is almost never what the operator wanted.
    use_auth_present = 'use_auth' in data
    username_present = 'username' in data
    if use_auth_present and _is_true(data.get('use_auth')):
        # On PUT, the username might already be set in the DB — only flag
        # the explicit "auth on, username empty" combo from the same payload.
        if username_present and not (data.get('username') or '').strip():
            return 'use_auth=True requires a non-empty username'
        if not partial and not (data.get('username') or '').strip():
            return 'use_auth=True requires a non-empty username'

    # Port must be a sane integer. Catches "" / negative / non-numeric.
    if 'port' in data:
        try:
            p = int(data['port'])
            if not (1 <= p <= 65535):
                return 'port must be between 1 and 65535'
        except (TypeError, ValueError):
            return 'port must be a number'

    # Password length cap — encryption services can choke on extremely
    # long inputs; column is String(500) so we'd overflow anyway.
    if 'password' in data and data['password'] is not None:
        if len(str(data['password'])) > 256:
            return 'password is too long (max 256 chars)'

    return None


@api_bp.route('/smtp', methods=['GET'])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_smtp():
    """List all configured SMTP servers."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        servers = repo.get_all()
        return jsonify({'servers': [s.to_dict() for s in servers]})


@api_bp.route('/smtp', methods=['POST'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_add_smtp():
    """Add a new SMTP server configuration."""
    data = request.get_json(silent=True) or {}

    if not data.get('host'):
        return jsonify({'error': 'Host required'}), 400

    err = _validate_smtp_payload(data, partial=False)
    if err:
        return jsonify({'error': err}), 400

    # Resolve tls_mode for the new row: explicit field wins, else derive
    # from legacy booleans, else default 'starttls'.
    tls_mode = data.get('tls_mode')
    if tls_mode not in ('none', 'starttls', 'ssl'):
        if data.get('use_ssl'):
            tls_mode = 'ssl'
        elif data.get('use_tls', True):
            tls_mode = 'starttls'
        else:
            tls_mode = 'none'

    try:
        service = SMTPService()
        server = service.add_server(
            name=data.get('name', data.get('host')),
            host=data['host'],
            port=int(data.get('port', 587)),
            username=data.get('username', ''),
            password=data.get('password', ''),
            use_tls=(tls_mode == 'starttls'),
            use_ssl=(tls_mode == 'ssl'),
            tls_mode=tls_mode,
            # Declare which address this server is authorized to send From.
            # When set on multiple servers, the connection pool routes by
            # From-ownership so a rotated From doesn't get routed through a
            # server that doesn't own it (gateways reject with 5.7.0).
            from_email=(data.get('from_email') or '').strip(),
            from_name=(data.get('from_name') or '').strip(),
        )
    except RuntimeError as e:
        # Password encryption failure now raises (was a silent plaintext
        # fallback). Surface a clear error rather than persisting bad data.
        return jsonify({'error': str(e)}), 500

    return jsonify({'success': True, 'server': server.to_dict()})


@api_bp.route('/smtp/test/<name>', methods=['POST'])
@api_bp.route('/smtp/test/<int:server_id>', methods=['POST'], endpoint='api_test_smtp_by_id')
@api_key_or_login_required
@limiter.limit("5/minute")
def api_test_smtp(name: str | None = None, server_id: int | None = None):
    """Test connection to a specific SMTP server.

    Accepts either the server name (preferred — matches PUT/DELETE
    `/api/smtp/<name>`) or a numeric id (kept for back-compat with any
    older client). The frontend (smtp.html) sends the name.
    """
    with session_scope() as session:
        repo = SMTPRepository(session)
        if server_id is not None:
            server = repo.get(server_id)
        else:
            server = repo.get_by_name(name)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404

        servers = repo.get_all()
        service = SMTPService()
        service.load_from_config([s.get_connection_config() for s in servers])

        result = run_async(service.test_connection(server.name))
        return jsonify(result)


@api_bp.route('/smtp/<name>', methods=['PUT'])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_update_smtp(name):
    """Update an existing SMTP server by name."""
    data = request.get_json(silent=True) or {}

    err = _validate_smtp_payload(data, partial=True)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404

        # Cross-field check that needs the post-merge state: if the
        # request turns auth on without touching username AND the stored
        # username is empty, reject. The partial validator can't see this
        # because it only inspects ``data``.
        if 'use_auth' in data and bool(data['use_auth']):
            effective_user = data.get('username', server.username) or ''
            if not effective_user.strip():
                return jsonify({
                    'success': False,
                    'error': 'use_auth=True requires a non-empty username',
                }), 400

        if 'host' in data:
            server.host = data['host']
        if 'port' in data:
            server.port = int(data['port'])
        if 'username' in data:
            server.username = data['username']
        if 'from_email' in data:
            server.from_email = (data.get('from_email') or '').strip()
        if 'from_name' in data:
            server.from_name = (data.get('from_name') or '').strip()
        if 'password' in data and data['password']:
            try:
                server.password = data['password']
            except RuntimeError as e:
                return jsonify({'success': False, 'error': str(e)}), 500
        # tls_mode is preferred; if absent, derive from legacy bools and
        # apply via set_tls_mode so use_tls/use_ssl stay in lockstep.
        new_mode: Optional[str] = None
        if 'tls_mode' in data and data['tls_mode'] in ('none', 'starttls', 'ssl'):
            new_mode = data['tls_mode']
        elif 'use_tls' in data or 'use_ssl' in data:
            new_use_ssl = bool(data.get('use_ssl', server.use_ssl))
            new_use_tls = bool(data.get('use_tls', server.use_tls))
            new_mode = 'ssl' if new_use_ssl else ('starttls' if new_use_tls else 'none')
        if new_mode is not None:
            server.set_tls_mode(new_mode)
        if 'use_auth' in data:
            server.use_auth = bool(data['use_auth'])
        repo.update(server)

        # Propagate the credential / TLS / endpoint change into any
        # in-flight connection pools. Without this, running campaigns
        # keep authenticating with the pre-update config until restart.
        try:
            from ....engine.connection_pool import (
                iter_active_pools, SMTPServerConfig,
            )
            fresh = SMTPServerConfig.from_dict(server.get_connection_config())
            for pool in iter_active_pools():
                run_async(pool.invalidate_server(server.name, new_config=fresh))
        except Exception:
            # Best-effort: the DB write succeeded; pool refresh failing
            # should not 500 the API call. Worker restart will pick up
            # the new config regardless.
            pass

        return jsonify({'success': True, 'server': server.to_dict()})


@api_bp.route('/smtp/<name>', methods=['DELETE'])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_smtp(name):
    """Delete a specific SMTP server by name."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404
        repo.delete(server)
        return jsonify({'success': True})
