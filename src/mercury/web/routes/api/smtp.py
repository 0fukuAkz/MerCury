"""SMTP server management API routes."""

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

    service = SMTPService()
    server = service.add_server(
        name=data.get('name', data.get('host')),
        host=data['host'],
        port=data.get('port', 587),
        username=data.get('username', ''),
        password=data.get('password', ''),
        use_tls=data.get('use_tls', True),
    )

    return jsonify({'success': True, 'server': server.to_dict()})


@api_bp.route('/smtp/test/<int:server_id>', methods=['POST'])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_test_smtp(server_id: int):
    """Test connection to a specific SMTP server by id."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get(server_id)
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
    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({'success': False, 'error': 'Server not found'}), 404
        if 'host' in data:
            server.host = data['host']
        if 'port' in data:
            server.port = int(data['port'])
        if 'username' in data:
            server.username = data['username']
        if 'password' in data and data['password']:
            server.password = data['password']
        if 'use_tls' in data:
            server.use_tls = bool(data['use_tls'])
        if 'use_ssl' in data:
            server.use_ssl = bool(data['use_ssl'])
        repo.update(server)
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
