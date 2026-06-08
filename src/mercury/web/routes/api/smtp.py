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
        return v in (True, "true", "True", 1, "1", "on")

    # tls_mode is the single TLS field. The legacy use_tls / use_ssl
    # booleans are rejected outright — clients must migrate.
    if "tls_mode" in data:
        if data["tls_mode"] not in ("none", "starttls", "ssl"):
            return "tls_mode must be one of 'none', 'starttls', 'ssl'"
    if "use_tls" in data or "use_ssl" in data:
        return (
            "use_tls / use_ssl are no longer accepted. Use tls_mode "
            "('none' | 'starttls' | 'ssl') instead."
        )

    # use_auth=True with no username silently degrades to anonymous send
    # at connect time, which is almost never what the operator wanted.
    use_auth_present = "use_auth" in data
    username_present = "username" in data
    if use_auth_present and _is_true(data.get("use_auth")):
        # On PUT, the username might already be set in the DB — only flag
        # the explicit "auth on, username empty" combo from the same payload.
        if username_present and not (data.get("username") or "").strip():
            return "use_auth=True requires a non-empty username"
        if not partial and not (data.get("username") or "").strip():
            return "use_auth=True requires a non-empty username"

    # Port must be a sane integer. Catches "" / negative / non-numeric.
    if "port" in data:
        try:
            p = int(data["port"])
            if not (1 <= p <= 65535):
                return "port must be between 1 and 65535"
        except (TypeError, ValueError):
            return "port must be a number"

    # Password length cap — encryption services can choke on extremely
    # long inputs; column is String(500) so we'd overflow anyway.
    if "password" in data and data["password"] is not None:
        if len(str(data["password"])) > 256:
            return "password is too long (max 256 chars)"

    return None


@api_bp.route("/smtp", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_smtp():
    """List all configured SMTP servers."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        servers = repo.get_all()

        # Aggregate real-time rate limit counts and latencies from active connection pools
        minute_counts = {}
        handshake_latencies = {}
        send_latencies = {}
        try:
            from ....engine.connection_pool import iter_active_pools

            active_pools = iter_active_pools()
            for pool in active_pools:
                status = pool.get_status()
                for name, s_status in status.items():
                    minute_counts[name] = minute_counts.get(name, 0) + s_status.get(
                        "minute_count", 0
                    )
                    h_lat = s_status.get("avg_handshake_latency")
                    if h_lat is not None:
                        handshake_latencies[name] = h_lat
                    s_lat = s_status.get("avg_send_latency")
                    if s_lat is not None:
                        send_latencies[name] = s_lat
        except Exception:
            pass

        # Get accurate sent and failed counts from EmailLog
        from ....data.models.email_log import EmailLog, EmailStatus
        from sqlalchemy import func

        success_statuses = [
            EmailStatus.SENT.value,
            EmailStatus.DELIVERED.value,
            EmailStatus.OPENED.value,
            EmailStatus.CLICKED.value,
        ]
        failure_statuses = [EmailStatus.FAILED.value, EmailStatus.BOUNCED.value]

        log_stats = {}
        try:
            stmt = (
                session.query(EmailLog.smtp_server_name, EmailLog.status, func.count(EmailLog.id))
                .filter(EmailLog.smtp_server_name.is_not(None))
                .group_by(EmailLog.smtp_server_name, EmailLog.status)
            )

            for server_name, status, count in stmt.all():
                if server_name not in log_stats:
                    log_stats[server_name] = {"sent": 0, "failed": 0}
                if status in success_statuses:
                    log_stats[server_name]["sent"] += count
                elif status in failure_statuses:
                    log_stats[server_name]["failed"] += count
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(f"Failed to query EmailLog SMTP stats: {e}")

        # Update server statistics in memory + database
        updated = False
        for s in servers:
            if s.name in log_stats:
                new_sent = log_stats[s.name]["sent"]
                new_failed = log_stats[s.name]["failed"]
            else:
                new_sent = 0
                new_failed = 0

            if s.total_sent != new_sent or s.total_failed != new_failed:
                s.total_sent = new_sent
                s.total_failed = new_failed
                updated = True

        if updated:
            try:
                session.commit()
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Failed to commit updated SMTP stats: {e}")
                session.rollback()

        result = []
        for s in servers:
            s_dict = s.to_dict()
            s_dict["current_minute_count"] = minute_counts.get(s.name, 0)
            s_dict["avg_handshake_latency"] = handshake_latencies.get(s.name)
            s_dict["avg_send_latency"] = send_latencies.get(s.name)
            result.append(s_dict)

        return jsonify({"servers": result})


@api_bp.route("/smtp", methods=["POST"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_add_smtp():
    """Add a new SMTP server configuration."""
    data = request.get_json(silent=True) or {}

    if not data.get("host"):
        return jsonify({"error": "Host required"}), 400

    err = _validate_smtp_payload(data, partial=False)
    if err:
        return jsonify({"error": err}), 400

    # tls_mode is required by the validator above; default to 'starttls'
    # when omitted entirely for a sensible greenfield-config baseline.
    tls_mode = data.get("tls_mode") or "starttls"

    try:
        service = SMTPService()
        server = service.add_server(
            name=data.get("name", data.get("host")),
            host=data["host"],
            port=int(data.get("port", 587)),
            username=data.get("username", ""),
            password=data.get("password", ""),
            tls_mode=tls_mode,
            # Declare which address this server is authorized to send From.
            # When set on multiple servers, the connection pool routes by
            # From-ownership so a rotated From doesn't get routed through a
            # server that doesn't own it (gateways reject with 5.7.0).
            from_email=(data.get("from_email") or "").strip(),
            from_name=(data.get("from_name") or "").strip(),
        )
    except RuntimeError as e:
        # Password encryption failure now raises (was a silent plaintext
        # fallback). Surface a clear error rather than persisting bad data.
        return jsonify({"error": str(e)}), 500

    return jsonify({"success": True, "server": server.to_dict()})


@api_bp.route("/smtp/test/<name>", methods=["POST"])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_test_smtp(name: str):
    """Test connection to a specific SMTP server by name statefully."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({"success": False, "error": "Server not found"}), 404

        servers = repo.get_all()
        service = SMTPService()
        service.load_from_config([s.get_connection_config() for s in servers])

        result = run_async(service.check_server_health(server.name))
        return jsonify(result)


@api_bp.route("/smtp/<name>", methods=["PUT"])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_update_smtp(name):
    """Update an existing SMTP server by name."""
    data = request.get_json(silent=True) or {}

    err = _validate_smtp_payload(data, partial=True)
    if err:
        return jsonify({"success": False, "error": err}), 400

    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({"success": False, "error": "Server not found"}), 404

        # Cross-field check that needs the post-merge state: if the
        # request turns auth on without touching username AND the stored
        # username is empty, reject. The partial validator can't see this
        # because it only inspects ``data``.
        if "use_auth" in data and bool(data["use_auth"]):
            effective_user = data.get("username", server.username) or ""
            if not effective_user.strip():
                return jsonify(
                    {
                        "success": False,
                        "error": "use_auth=True requires a non-empty username",
                    }
                ), 400

        if "name" in data and data["name"].strip():
            new_name = data["name"].strip()
            if new_name != server.name:
                existing = repo.get_by_name(new_name)
                if existing:
                    return jsonify(
                        {"success": False, "error": f"Server name '{new_name}' is already in use"}
                    ), 400
                server.name = new_name

        if "host" in data:
            server.host = data["host"]
        if "port" in data:
            server.port = int(data["port"])
        if "username" in data:
            server.username = data["username"]
        if "from_email" in data:
            server.from_email = (data.get("from_email") or "").strip()
        if "from_name" in data:
            server.from_name = (data.get("from_name") or "").strip()
        if "password" in data and data["password"]:
            try:
                server.password = data["password"]
            except RuntimeError as e:
                return jsonify({"success": False, "error": str(e)}), 500
        # Only tls_mode is accepted; legacy bools are rejected by the validator.
        if "tls_mode" in data and data["tls_mode"] in ("none", "starttls", "ssl"):
            server.set_tls_mode(data["tls_mode"])
        if "use_auth" in data:
            server.use_auth = bool(data["use_auth"])
        repo.update(server)

        # Propagate the credential / TLS / endpoint change into any
        # in-flight connection pools. Without this, running campaigns
        # keep authenticating with the pre-update config until restart.
        try:
            from ....engine.connection_pool import (
                iter_active_pools,
                SMTPServerConfig,
            )

            fresh = SMTPServerConfig.from_dict(server.get_connection_config())
            for pool in iter_active_pools():
                run_async(pool.invalidate_server(server.name, new_config=fresh))
        except Exception:
            # Best-effort: the DB write succeeded; pool refresh failing
            # should not 500 the API call. Worker restart will pick up
            # the new config regardless.
            pass

        return jsonify({"success": True, "server": server.to_dict()})


@api_bp.route("/smtp/<name>", methods=["DELETE"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_smtp(name):
    """Delete a specific SMTP server by name."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        server = repo.get_by_name(name)
        if not server:
            return jsonify({"success": False, "error": "Server not found"}), 404
        repo.delete(server)
        return jsonify({"success": True})


@api_bp.route("/smtp/health", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_smtp_health_status():
    """Get the latest health checks status of all configured SMTP servers."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        servers = repo.get_all()
        return jsonify(
            {
                "servers": [
                    {
                        "name": s.name,
                        "host": s.host,
                        "port": s.port,
                        "status": s.status,
                        "is_enabled": s.is_enabled,
                        "last_checked_at": (s.settings or {}).get("last_checked_at"),
                        "health_error": (s.settings or {}).get("health_error"),
                        "health_error_type": (s.settings or {}).get("health_error_type"),
                    }
                    for s in servers
                ]
            }
        )


@api_bp.route("/smtp/health/check", methods=["POST"])
@api_key_or_login_required
@limiter.limit("5/minute")
def api_trigger_smtp_health_checks():
    """Manually trigger background health checks on all active SMTP servers."""
    with session_scope() as session:
        repo = SMTPRepository(session)
        servers = repo.get_all()
        configs = [s.get_connection_config() for s in servers if s.is_enabled]

    if not configs:
        return jsonify({"success": False, "error": "No enabled SMTP servers configured"}), 400

    service = SMTPService()
    service.load_from_config(configs)

    results = run_async(service.check_all_health())
    return jsonify({"success": True, "results": results})
