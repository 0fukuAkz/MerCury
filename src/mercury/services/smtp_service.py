"""SMTP service for managing SMTP connections and sending."""

import logging
from typing import List, Dict, Any, Optional

from ..data.database import get_session_direct
from ..data.repositories import SMTPRepository
from ..data.models import SMTPServer
from ..engine.connection_pool import SMTPConnectionPool, SMTPServerConfig

logger = logging.getLogger(__name__)


class SMTPService:
    """Service for managing SMTP servers and connections."""

    def __init__(self):
        self._connection_pool: Optional[SMTPConnectionPool] = None
        self._configs: List[SMTPServerConfig] = []

    def load_from_database(self, server_id: Optional[int] = None) -> List[SMTPServerConfig]:
        """Load SMTP configs from database.

        If ``server_id`` is provided, only that one server is loaded (used by
        campaigns that pin a specific SMTP server via the campaign-form
        dropdown). The server must still be enabled — a disabled pinned
        server falls through to an empty list, which initialize() treats as
        "no servers" and surfaces as a campaign error rather than silently
        rotating across other servers the operator didn't pick.
        """
        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            if server_id is not None:
                _one = repo.get(server_id)
                servers = [_one] if (_one and _one.is_enabled) else []
            else:
                servers = repo.get_active()

            self._configs = [
                SMTPServerConfig(
                    name=server.name,
                    host=server.host,
                    port=server.port,
                    username=server.username,
                    password=server.password,
                    tls_mode=server.tls_mode or "starttls",
                    use_auth=server.use_auth,
                    timeout=server.timeout,
                    from_email=server.from_email or "",
                    from_name=server.from_name or "",
                    weight=server.weight,
                    priority=server.priority,
                    max_per_minute=server.max_per_minute,
                    max_per_hour=server.max_per_hour,
                )
                for server in servers
            ]

            logger.info(f"Loaded {len(self._configs)} SMTP servers from database")
            return self._configs

        finally:
            session.close()

    def load_from_config(self, smtp_configs: List[Dict[str, Any]]) -> List[SMTPServerConfig]:
        """Load SMTP configs from configuration dict."""
        self._configs = [SMTPServerConfig.from_dict(config) for config in smtp_configs]

        logger.info(f"Loaded {len(self._configs)} SMTP servers from config")
        return self._configs

    def get_connection_pool(
        self,
        pool_size_per_server: int = 5,
        selection_strategy: str = "weighted",
        ip_warmup_mode: bool = False,
    ) -> SMTPConnectionPool:
        """Get or create connection pool."""
        if not self._configs:
            raise RuntimeError("No SMTP servers configured")

        if self._connection_pool is None:
            self._connection_pool = SMTPConnectionPool(
                configs=self._configs,
                pool_size_per_server=pool_size_per_server,
                selection_strategy=selection_strategy,
                ip_warmup_mode=ip_warmup_mode,
            )

        return self._connection_pool

    async def test_connection(self, server_name: str) -> Dict[str, Any]:
        """Test connection to a specific SMTP server.

        Walks the stages explicitly so the response distinguishes:
          - tcp_failed: couldn't reach the host
          - tls_failed: STARTTLS / implicit-SSL handshake failed
          - auth_failed: credentials rejected
          - protocol_failed: other SMTP-level rejection

        The previous implementation returned a single generic "Connection
        successful" even when AUTH was effectively a no-op (use_auth=True
        with no username silently skipped login), and exposed raw
        ``str(e)`` which can leak relay banners or internal hostnames.
        """
        import aiosmtplib

        config = next((c for c in self._configs if c.name == server_name), None)
        if not config:
            return {
                "success": False,
                "server": server_name,
                "error": "Server not found",
                "stage": "lookup",
            }

        # Catch the use_auth=True + empty username case before opening a
        # socket — the connect path silently skips login, which makes a
        # successful test misleading.
        if config.use_auth and not config.username:
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": "config",
                "error_type": "misconfigured_auth",
                "error": "use_auth=True but no username is set",
            }

        from ..engine.connection_pool import AsyncSMTPConnection  # noqa: F401

        mode = config.tls_mode
        client: aiosmtplib.SMTP | None = None
        stage = "tcp"
        try:
            implicit_tls = mode == "ssl"
            client = aiosmtplib.SMTP(
                hostname=config.host,
                port=config.port,
                use_tls=implicit_tls,
                timeout=config.timeout,
            )
            await client.connect()

            if mode == "starttls":
                # aiosmtplib.starttls() issues the post-upgrade EHLO
                # internally (RFC 3207 requires it). Sending a second
                # EHLO here used to be the iCloud-failure path: AWS
                # SES tolerates the duplicate, but iCloud and some
                # strict Postfix configs reject the second EHLO with a
                # 503 "bad sequence" / 550. Trust starttls() to leave
                # the session in an EHLO'd state.
                stage = "tls"
                await client.starttls()
            else:
                # No STARTTLS upgrade happened, so connect() didn't
                # leave us with an EHLO'd session — send one now.
                stage = "ehlo"
                await client.ehlo()

            auth_attempted = False
            if config.use_auth and config.username:
                stage = "auth"
                await client.login(config.username, config.password)
                auth_attempted = True

            return {
                "success": True,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "tls_mode": mode,
                "auth_verified": auth_attempted,
                "message": "Connection + AUTH verified"
                if auth_attempted
                else "Connection verified (no auth attempted)",
            }

        except aiosmtplib.SMTPAuthenticationError as e:
            # Authenticated endpoint, so include the relay's actual
            # response (truncated) — operators need this to tell
            # "wrong password" from "app-specific password required"
            # from "user disabled".
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": "auth",
                "error_type": "auth_failed",
                "error": f'Authentication rejected ({getattr(e, "code", "n/a")})',
                "details": str(e)[:300],
            }
        except aiosmtplib.SMTPConnectTimeoutError as e:
            # Distinct from generic connect error: the TCP handshake
            # started but the relay didn't respond in time. Common
            # for iCloud over IPv6 when the AAAA path isn't routable
            # (Python tries v6 first by default and waits the full
            # timeout before falling back).
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": stage,
                "error_type": "tcp_timeout",
                "error": f"Timed out connecting to {config.host}:{config.port} after {config.timeout}s",
                "details": str(e)[:300],
                "hint": (
                    "If this server worked from elsewhere, the most common cause is an IPv6 "
                    "routing problem: Python tries the AAAA record first and waits the full "
                    "timeout before falling back to IPv4. Workaround: set the server `timeout` "
                    "lower (e.g. 10s) so the v6 path fails fast and v4 kicks in, or run on a "
                    "host with working IPv6."
                ),
            }
        except aiosmtplib.SMTPConnectResponseError as e:
            # TCP succeeded, but the server's greeting wasn't a 220.
            # Usually means we're connected to the right port but the
            # server is rejecting us (rate-limited, IP-blocked,
            # protocol mismatch).
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": stage,
                "error_type": "bad_greeting",
                "error": f'Connected but greeting was not 220 ({getattr(e, "code", "n/a")})',
                "details": str(e)[:300],
            }
        except aiosmtplib.SMTPConnectError as e:
            # Generic connect failure: DNS failure, connection refused,
            # network unreachable, etc. The `details` text is what
            # actually tells you which — without it, the operator is
            # guessing.
            #
            # We sniff for DNS-failure signatures specifically because
            # that's the most actionable diagnosis ("change your DNS
            # resolver") and the most common confused-with-firewall
            # cause. Real example seen in the wild: consumer routers
            # return SERVFAIL for smtp.mail.me.com while resolving
            # AWS SES hosts fine, so iCloud fails and AWS works.
            err_text = str(e).lower()
            dns_signatures = (
                "nodename nor servname",  # macOS getaddrinfo
                "name or service not known",  # Linux getaddrinfo
                "temporary failure in name resolution",
                "no address associated with hostname",
                "getaddrinfo failed",  # generic
            )
            if any(sig in err_text for sig in dns_signatures):
                return {
                    "success": False,
                    "server": server_name,
                    "host": config.host,
                    "port": config.port,
                    "stage": stage,
                    "error_type": "dns_failure",
                    "error": f"Hostname {config.host} does not resolve via system DNS",
                    "details": str(e)[:300],
                    "hint": (
                        f"Your DNS resolver cannot resolve {config.host}. Try: "
                        f"(1) `dig @8.8.8.8 {config.host}` to verify Google's DNS sees it; "
                        f"(2) if (1) works, change your DNS resolver — on macOS: "
                        f"`networksetup -setdnsservers Wi-Fi 8.8.8.8 8.8.4.4`; "
                        f"(3) some consumer routers have stale Apple/Microsoft subdomain "
                        f"entries — switching to 1.1.1.1 / 8.8.8.8 fixes it."
                    ),
                }
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": stage,
                "error_type": "tcp_failed",
                "error": f"Could not connect to {config.host}:{config.port}",
                "details": str(e)[:300] or f"{type(e).__name__} (no message)",
                "hint": (
                    "Common causes: (1) port 587 outbound blocked by ISP/firewall — try "
                    "port 465 with tls_mode=ssl, or test from a different network; "
                    "(2) connection refused — verify the host/port are right; "
                    "(3) IPv6 path unreachable — see tcp_timeout hint if the symptom is timeouts."
                ),
            }
        except aiosmtplib.SMTPException as e:
            # Surface the actual SMTP response code + first 300 chars
            # of the message. This is the most common debug-blocker:
            # the old generic "SMTP protocol error" left operators with
            # no way to tell iCloud's 503-after-second-EHLO apart from
            # an Office365 throttle or a Postfix policy reject.
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": stage,
                "error_type": "protocol_failed",
                "error": f'SMTP protocol error ({getattr(e, "code", "n/a")})',
                "details": str(e)[:300],
            }
        except (OSError, TimeoutError) as e:
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": stage,
                "error_type": "tls_failed" if stage == "tls" else "tcp_failed",
                "error": f"Network failure during {stage}",
                "details": f"{type(e).__name__}: {str(e)[:200]}",
            }
        except Exception as e:
            # Log the raw text server-side for debugging; return a sanitized
            # message client-side. Raw str(e) can include relay banners or
            # internal addresses we don't want in REST responses.
            logger.exception(
                "Unexpected error testing SMTP server '%s' at stage '%s'",
                server_name,
                stage,
            )
            return {
                "success": False,
                "server": server_name,
                "host": config.host,
                "port": config.port,
                "stage": stage,
                "error_type": "unknown",
                "error": f"{type(e).__name__} during {stage}",
            }
        finally:
            if client is not None:
                try:
                    await client.quit()
                except Exception:
                    pass

    async def test_all_connections(self) -> List[Dict[str, Any]]:
        """Test all SMTP server connections."""
        results = []
        for config in self._configs:
            result = await self.test_connection(config.name)
            results.append(result)
        return results

    def add_server(
        self,
        name: str,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        tls_mode: str = "starttls",
        **kwargs,
    ) -> SMTPServer:
        """Add new SMTP server to database. ``tls_mode`` must be one of
        ``'none'`` / ``'starttls'`` / ``'ssl'``."""
        # Strip any legacy use_tls / use_ssl that an old caller still passes —
        # we deliberately don't honor them; if anyone hits this, they should
        # see the warning in tests and migrate to tls_mode.
        kwargs.pop("use_tls", None)
        kwargs.pop("use_ssl", None)
        session = get_session_direct()
        try:
            server = SMTPServer(
                name=name,
                host=host,
                port=port,
                username=username,
                password=password,
                **kwargs,
            )
            server.set_tls_mode(tls_mode)
            repo = SMTPRepository(session)
            return repo.create(server)
        finally:
            session.close()

    def remove_server(self, server_name: str) -> bool:
        """Remove SMTP server from database."""
        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            server = repo.get_by_name(server_name)
            if server:
                return repo.delete(server)
            return False

        finally:
            session.close()

    def get_server_status(self) -> List[Dict[str, Any]]:
        """Get status of all configured servers."""
        return [
            {
                "name": config.name,
                "host": config.host,
                "port": config.port,
                "circuit_state": config.runtime.circuit_breaker.get_stats()["state"],
                "available": config.can_execute(),
                "minute_count": config.runtime.current_minute_count,
                "max_per_minute": config.max_per_minute,
                "hour_count": config.runtime.current_hour_count,
                "max_per_hour": config.max_per_hour,
                "circuit_breaker_stats": config.runtime.circuit_breaker.get_stats(),
            }
            for config in self._configs
        ]

    async def close(self):
        """Close connection pool."""
        if self._connection_pool:
            await self._connection_pool.close_all()
            self._connection_pool = None

    async def check_all_health(self) -> List[Dict[str, Any]]:
        """Run health checks on all loaded SMTP servers.

        Updates their status (ACTIVE/ERROR) and health metrics in the database,
        emits socket events for real-time dashboard updates, and invalidates
        any active connection pools if their status changes.
        """
        import datetime
        from ..data.database import get_session_direct
        from ..data.repositories.smtp import SMTPRepository
        from ..data.models.smtp import SMTPServerStatus
        from ..engine.connection_pool import iter_active_pools, SMTPServerConfig
        from ..web.extensions import queue_emit
        from sqlalchemy.orm.attributes import flag_modified

        results = []
        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            for config in self._configs:
                result = await self.test_connection(config.name)
                results.append(result)

                # Fetch DB model to update status
                server = repo.get_by_name(config.name)
                if server:
                    old_status = server.status
                    # Update status based on check
                    if result["success"]:
                        if server.status == SMTPServerStatus.ERROR.value:
                            server.status = SMTPServerStatus.ACTIVE.value

                        # Clear old error metadata
                        if not server.settings:
                            server.settings = {}
                        server.settings["last_checked_at"] = datetime.datetime.now(
                            datetime.UTC
                        ).isoformat()
                        server.settings.pop("health_error", None)
                        server.settings.pop("health_error_type", None)
                        server.settings.pop("health_details", None)
                    else:
                        server.status = SMTPServerStatus.ERROR.value
                        if not server.settings:
                            server.settings = {}
                        server.settings["last_checked_at"] = datetime.datetime.now(
                            datetime.UTC
                        ).isoformat()
                        server.settings["health_error"] = result.get(
                            "error", "Unknown health error"
                        )
                        server.settings["health_error_type"] = result.get(
                            "error_type", "tcp_failed"
                        )
                        server.settings["health_details"] = result.get("details", "")

                    flag_modified(server, "settings")
                    repo.update(server)

                    # If status changed, invalidate the server in all active pools
                    if server.status != old_status:
                        logger.info(
                            f"SMTP status changed for '{server.name}': {old_status} -> {server.status}. Invalidating active pools."
                        )
                        new_cfg_dict = server.get_connection_config()
                        new_cfg = SMTPServerConfig.from_dict(new_cfg_dict)
                        for pool in iter_active_pools():
                            await pool.invalidate_server(server.name, new_cfg)

            session.commit()

            # Emit Socket.IO event to update the UI
            try:
                queue_emit("smtp_health_updated", {"results": [r for r in results]})
            except Exception as e:
                logger.warning(f"Failed to queue emit smtp_health_updated: {e}")

        except Exception:
            logger.exception("Error during SMTP health check execution")
            session.rollback()
            raise
        finally:
            session.close()

        return results

    async def check_server_health(self, name: str) -> Dict[str, Any]:
        """Run health check on a specific SMTP server by name.

        Updates its status (ACTIVE/ERROR) and health metrics in the database,
        emits socket events for real-time dashboard updates, and invalidates
        any active connection pools if its status changes.
        """
        import datetime
        from ..data.database import get_session_direct
        from ..data.repositories.smtp import SMTPRepository
        from ..data.models.smtp import SMTPServerStatus
        from ..engine.connection_pool import iter_active_pools, SMTPServerConfig
        from ..web.extensions import queue_emit
        from sqlalchemy.orm.attributes import flag_modified

        result = await self.test_connection(name)

        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            server = repo.get_by_name(name)
            if server:
                old_status = server.status
                # Update status based on check
                if result["success"]:
                    if server.status == SMTPServerStatus.ERROR.value:
                        server.status = SMTPServerStatus.ACTIVE.value

                    # Clear old error metadata
                    if not server.settings:
                        server.settings = {}
                    server.settings["last_checked_at"] = datetime.datetime.now(
                        datetime.UTC
                    ).isoformat()
                    server.settings.pop("health_error", None)
                    server.settings.pop("health_error_type", None)
                    server.settings.pop("health_details", None)
                else:
                    server.status = SMTPServerStatus.ERROR.value
                    if not server.settings:
                        server.settings = {}
                    server.settings["last_checked_at"] = datetime.datetime.now(
                        datetime.UTC
                    ).isoformat()
                    server.settings["health_error"] = result.get("error", "Unknown health error")
                    server.settings["health_error_type"] = result.get("error_type", "tcp_failed")
                    server.settings["health_details"] = result.get("details", "")

                flag_modified(server, "settings")
                repo.update(server)

                # If status changed, invalidate the server in all active pools
                if server.status != old_status:
                    logger.info(
                        f"SMTP status changed for '{server.name}': {old_status} -> {server.status}. Invalidating active pools."
                    )
                    new_cfg_dict = server.get_connection_config()
                    new_cfg = SMTPServerConfig.from_dict(new_cfg_dict)
                    for pool in iter_active_pools():
                        await pool.invalidate_server(server.name, new_cfg)

            session.commit()

            # Emit Socket.IO event to update the UI
            try:
                queue_emit("smtp_health_updated", {"results": [result]})
            except Exception as e:
                logger.warning(f"Failed to queue emit smtp_health_updated: {e}")

        except Exception:
            logger.exception(f"Error during SMTP server '{name}' health check execution")
            session.rollback()
            raise
        finally:
            session.close()

        return result
