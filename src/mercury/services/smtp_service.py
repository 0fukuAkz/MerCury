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
                    tls_mode=server.tls_mode or 'starttls',
                    use_auth=server.use_auth,
                    timeout=server.timeout,
                    from_email=server.from_email or "",
                    from_name=server.from_name or "",
                    weight=server.weight,
                    priority=server.priority,
                    max_per_minute=server.max_per_minute,
                    max_per_hour=server.max_per_hour
                )
                for server in servers
            ]
            
            logger.info(f"Loaded {len(self._configs)} SMTP servers from database")
            return self._configs
            
        finally:
            session.close()
    
    def load_from_config(self, smtp_configs: List[Dict[str, Any]]) -> List[SMTPServerConfig]:
        """Load SMTP configs from configuration dict."""
        self._configs = [
            SMTPServerConfig.from_dict(config)
            for config in smtp_configs
        ]
        
        logger.info(f"Loaded {len(self._configs)} SMTP servers from config")
        return self._configs
    
    def get_connection_pool(
        self,
        pool_size_per_server: int = 5,
        selection_strategy: str = 'weighted'
    ) -> SMTPConnectionPool:
        """Get or create connection pool."""
        if not self._configs:
            raise RuntimeError("No SMTP servers configured")
        
        if self._connection_pool is None:
            self._connection_pool = SMTPConnectionPool(
                configs=self._configs,
                pool_size_per_server=pool_size_per_server,
                selection_strategy=selection_strategy
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
                'success': False,
                'server': server_name,
                'error': 'Server not found',
                'stage': 'lookup',
            }

        # Catch the use_auth=True + empty username case before opening a
        # socket — the connect path silently skips login, which makes a
        # successful test misleading.
        if config.use_auth and not config.username:
            return {
                'success': False,
                'server': server_name,
                'host': config.host,
                'port': config.port,
                'stage': 'config',
                'error_type': 'misconfigured_auth',
                'error': 'use_auth=True but no username is set',
            }

        from ..engine.connection_pool import AsyncSMTPConnection  # noqa: F401
        mode = config.tls_mode
        client: aiosmtplib.SMTP | None = None
        stage = 'tcp'
        try:
            implicit_tls = (mode == 'ssl')
            client = aiosmtplib.SMTP(
                hostname=config.host,
                port=config.port,
                use_tls=implicit_tls,
                timeout=config.timeout,
            )
            await client.connect()

            if mode == 'starttls':
                stage = 'tls'
                await client.starttls()

            stage = 'ehlo'
            await client.ehlo()

            auth_attempted = False
            if config.use_auth and config.username:
                stage = 'auth'
                await client.login(config.username, config.password)
                auth_attempted = True

            return {
                'success': True,
                'server': server_name,
                'host': config.host,
                'port': config.port,
                'tls_mode': mode,
                'auth_verified': auth_attempted,
                'message': 'Connection + AUTH verified' if auth_attempted else 'Connection verified (no auth attempted)',
            }

        except aiosmtplib.SMTPAuthenticationError as e:
            return {
                'success': False, 'server': server_name, 'host': config.host, 'port': config.port,
                'stage': 'auth', 'error_type': 'auth_failed',
                'error': f'Authentication rejected ({getattr(e, "code", "n/a")})',
            }
        except aiosmtplib.SMTPConnectError:
            return {
                'success': False, 'server': server_name, 'host': config.host, 'port': config.port,
                'stage': stage, 'error_type': 'tcp_failed',
                'error': 'Could not connect to host (TCP or DNS failure)',
            }
        except aiosmtplib.SMTPException as e:
            return {
                'success': False, 'server': server_name, 'host': config.host, 'port': config.port,
                'stage': stage, 'error_type': 'protocol_failed',
                'error': f'SMTP protocol error ({getattr(e, "code", "n/a")})',
            }
        except (OSError, TimeoutError):
            return {
                'success': False, 'server': server_name, 'host': config.host, 'port': config.port,
                'stage': stage, 'error_type': 'tls_failed' if stage == 'tls' else 'tcp_failed',
                'error': f'Network failure during {stage}',
            }
        except Exception as e:
            # Log the raw text server-side for debugging; return a sanitized
            # message client-side. Raw str(e) can include relay banners or
            # internal addresses we don't want in REST responses.
            logger.exception(
                "Unexpected error testing SMTP server '%s' at stage '%s'",
                server_name, stage,
            )
            return {
                'success': False, 'server': server_name, 'host': config.host, 'port': config.port,
                'stage': stage, 'error_type': 'unknown',
                'error': f'{type(e).__name__} during {stage}',
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
        tls_mode: str = 'starttls',
        **kwargs,
    ) -> SMTPServer:
        """Add new SMTP server to database. ``tls_mode`` must be one of
        ``'none'`` / ``'starttls'`` / ``'ssl'``."""
        # Strip any legacy use_tls / use_ssl that an old caller still passes —
        # we deliberately don't honor them; if anyone hits this, they should
        # see the warning in tests and migrate to tls_mode.
        kwargs.pop('use_tls', None)
        kwargs.pop('use_ssl', None)
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
                'name': config.name,
                'host': config.host,
                'port': config.port,
                'circuit_state': config.runtime.circuit_breaker.get_stats()['state'],
                'available': config.can_execute(),
                'minute_count': config.runtime.current_minute_count,
                'max_per_minute': config.max_per_minute,
                'hour_count': config.runtime.current_hour_count,
                'max_per_hour': config.max_per_hour,
                'circuit_breaker_stats': config.runtime.circuit_breaker.get_stats()
            }
            for config in self._configs
        ]
    
    async def close(self):
        """Close connection pool."""
        if self._connection_pool:
            await self._connection_pool.close_all()
            self._connection_pool = None

