"""SMTP service for managing SMTP connections and sending."""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, UTC

from ..data.database import get_session_direct
from ..data.repositories import SMTPRepository
from ..data.models import SMTPServer, SMTPServerStatus
from ..engine.connection_pool import SMTPConnectionPool, SMTPServerConfig

logger = logging.getLogger(__name__)


class SMTPService:
    """Service for managing SMTP servers and connections."""
    
    def __init__(self):
        self._connection_pool: Optional[SMTPConnectionPool] = None
        self._configs: List[SMTPServerConfig] = []
    
    def load_from_database(self) -> List[SMTPServerConfig]:
        """Load SMTP configs from database."""
        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            servers = repo.get_active()
            
            self._configs = [
                SMTPServerConfig(
                    name=server.name,
                    host=server.host,
                    port=server.port,
                    username=server.username,
                    password=server.password,
                    use_tls=server.use_tls,
                    use_ssl=server.use_ssl,
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
        """
        Test connection to specific SMTP server.
        
        Returns:
            Dict with test results
        """
        config = next((c for c in self._configs if c.name == server_name), None)
        if not config:
            return {
                'success': False,
                'server': server_name,
                'error': 'Server not found'
            }
        
        try:
            from ..engine.connection_pool import AsyncSMTPConnection
            
            conn = AsyncSMTPConnection(config)
            await conn.connect()
            await conn.close()
            
            return {
                'success': True,
                'server': server_name,
                'host': config.host,
                'port': config.port,
                'message': 'Connection successful'
            }
            
        except Exception as e:
            return {
                'success': False,
                'server': server_name,
                'host': config.host,
                'port': config.port,
                'error': str(e)
            }
    
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
        use_tls: bool = True,
        **kwargs
    ) -> SMTPServer:
        """Add new SMTP server to database."""
        session = get_session_direct()
        try:
            server = SMTPServer(
                name=name,
                host=host,
                port=port,
                username=username,
                password=password,
                use_tls=use_tls,
                **kwargs
            )
            
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
                'circuit_state': config.circuit_breaker.get_stats()['state'],
                'available': config.can_execute(),
                'minute_count': config.current_minute_count,
                'max_per_minute': config.max_per_minute,
                'hour_count': config.current_hour_count,
                'max_per_hour': config.max_per_hour,
                'circuit_breaker_stats': config.circuit_breaker.get_stats()
            }
            for config in self._configs
        ]
    
    async def close(self):
        """Close connection pool."""
        if self._connection_pool:
            await self._connection_pool.close_all()
            self._connection_pool = None

