"""SMTP connection pooling with circuit breaker and load balancing."""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, UTC
from dataclasses import dataclass, field
import aiosmtplib

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig

logger = logging.getLogger(__name__)


class ConnectionPoolException(Exception):
    """Errors related to connection pool operations."""
    pass


def _create_circuit_breaker(server_name: str = "default") -> CircuitBreaker:
    """Factory function to create a circuit breaker with default config."""
    return CircuitBreaker(
        server_name=server_name,
        config=CircuitBreakerConfig(
            failure_threshold=5,
            success_threshold=3,
            timeout_seconds=60,
            monitor_window_seconds=300
        )
    )


@dataclass
class SMTPServerConfig:
    """SMTP server configuration."""
    name: str
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    use_ssl: bool = False
    use_auth: bool = True
    timeout: int = 30
    from_email: str = ""
    from_name: str = ""
    weight: float = 1.0
    priority: int = 0
    max_per_minute: int = 30
    max_per_hour: int = 500
    
    # Runtime state - circuit_breaker will be initialized in __post_init__
    circuit_breaker: CircuitBreaker = field(default=None)
    current_minute_count: int = 0
    current_hour_count: int = 0
    total_sent: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_minute_reset: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_hour_reset: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def __post_init__(self):
        """Initialize circuit breaker after dataclass initialization."""
        if self.circuit_breaker is None:
            self.circuit_breaker = _create_circuit_breaker(self.name)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SMTPServerConfig':
        """Create config from dictionary."""
        return cls(
            name=data.get('name', data.get('host', 'default')),
            host=data['host'],
            port=data.get('port', 587),
            username=data.get('username', ''),
            password=data.get('password', ''),
            use_tls=data.get('use_tls', True),
            use_ssl=data.get('use_ssl', False),
            use_auth=data.get('use_auth', True),
            timeout=data.get('timeout', 30),
            from_email=data.get('from_email', ''),
            from_name=data.get('from_name', ''),
            weight=data.get('weight', 1.0),
            priority=data.get('priority', 0),
            max_per_minute=data.get('max_per_minute', 30),
            max_per_hour=data.get('max_per_hour', 500),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'use_tls': self.use_tls,
            'use_ssl': self.use_ssl,
            'use_auth': self.use_auth,
            'timeout': self.timeout,
            'from_email': self.from_email,
            'from_name': self.from_name,
            'weight': self.weight,
            'priority': self.priority,
            'max_per_minute': self.max_per_minute,
            'max_per_hour': self.max_per_hour,
        }
    
    def check_rate_limits(self) -> bool:
        """Check if within rate limits."""
        now = datetime.now(UTC)
        
        # Reset minute counter
        if (now - self.last_minute_reset).total_seconds() >= 60:
            self.current_minute_count = 0
            self.last_minute_reset = now
        
        # Reset hour counter
        if (now - self.last_hour_reset).total_seconds() >= 3600:
            self.current_hour_count = 0
            self.last_hour_reset = now
        
        return (
            self.current_minute_count < self.max_per_minute and
            self.current_hour_count < self.max_per_hour
        )
    
    def increment_counters(self):
        """Increment rate limit counters."""
        self.current_minute_count += 1
        self.current_hour_count += 1
    
    def can_execute(self) -> bool:
        """Check if server can accept requests (circuit breaker + rate limits)."""
        return self.circuit_breaker.is_available() and self.check_rate_limits()


class AsyncSMTPConnection:
    """Async SMTP connection wrapper."""
    
    def __init__(self, config: SMTPServerConfig):
        self.config = config
        self.client: Optional[aiosmtplib.SMTP] = None
        self.is_connected = False
        self.created_at = datetime.now(UTC)
        self.last_used = datetime.now(UTC)
        self.messages_sent = 0
    
    async def connect(self) -> None:
        """Establish async SMTP connection."""
        use_tls_param = self.config.use_ssl or self.config.port == 465
        
        self.client = aiosmtplib.SMTP(
            hostname=self.config.host,
            port=self.config.port,
            use_tls=use_tls_param,
            timeout=self.config.timeout
        )
        
        await self.client.connect()
        
        # STARTTLS for port 587
        if self.config.use_tls and not use_tls_param:
            await self.client.starttls()
        
        if self.config.use_auth and self.config.username:
            await self.client.login(self.config.username, self.config.password)
        
        self.is_connected = True
        logger.debug(f"Connected to {self.config.name} ({self.config.host}:{self.config.port})")
    
    async def send_message(self, msg) -> Dict[str, Any]:
        """Send email message."""
        if not self.is_connected or not self.client:
            await self.connect()
        
        try:
            response = await self.client.send_message(msg)
            self.last_used = datetime.now(UTC)
            self.messages_sent += 1
            self.config.increment_counters()
            return {'success': True, 'response': str(response)}
        except Exception:
            self.is_connected = False
            raise
    
    async def close(self) -> None:
        """Close SMTP connection."""
        if self.client and self.is_connected:
            try:
                await self.client.quit()
            except Exception:
                pass
        self.is_connected = False
    
    @property
    def age_seconds(self) -> float:
        """Get connection age in seconds."""
        return (datetime.now(UTC) - self.created_at).total_seconds()
    
    @property
    def idle_seconds(self) -> float:
        """Get idle time in seconds."""
        return (datetime.now(UTC) - self.last_used).total_seconds()


class AsyncConnectionPool:
    """Async connection pool for single SMTP server."""
    
    def __init__(
        self, 
        config: SMTPServerConfig, 
        pool_size: int = 5,
        max_connection_age: float = 300.0,
        max_idle_time: float = 60.0
    ):
        self.config = config
        self.pool_size = pool_size
        self.max_connection_age = max_connection_age
        self.max_idle_time = max_idle_time
        
        self.connections: List[AsyncSMTPConnection] = []
        # Backward-compatible alias expected by tests
        self._connections = self.connections
        self.available: asyncio.Queue = asyncio.Queue()
        self.lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self):
        """Initialize the pool with connections."""
        if self._initialized:
            return
        
        async with self.lock:
            if self._initialized:
                return
            
            for _ in range(min(2, self.pool_size)):  # Start with 2 connections
                try:
                    conn = AsyncSMTPConnection(self.config)
                    await conn.connect()
                    self.connections.append(conn)
                    await self.available.put(conn)
                except Exception as e:
                    logger.warning(f"Failed to create initial connection: {e}")
            
            self._initialized = True
    
    async def _replenish_one(self):
        """
        Proactively create a new connection if under pool limits.
        
        This prevents waiters from blocking on timeout when a stale 
        connection is discarded.
        """
        async with self.lock:
            if len(self.connections) >= self.pool_size:
                return

            try:
                conn = AsyncSMTPConnection(self.config)
                await conn.connect()
                self.connections.append(conn)
                await self.available.put(conn)
                logger.debug(f"Replenished connection pool for {self.config.name}")
            except Exception as e:
                logger.warning(f"Failed to replenish connection: {e}")
                # Don't raise, we'll try again later naturally

    
    async def get_connection(self, timeout: float = 10.0) -> AsyncSMTPConnection:
        """Get a connection from the pool."""
        await self.initialize()
        
        try:
            # Try to get existing connection
            conn = await asyncio.wait_for(self.available.get(), timeout=timeout/2)
            
            # Check if connection is still valid
            if (
                not conn.is_connected
                or conn.age_seconds > self.max_connection_age
                or conn.idle_seconds > self.max_idle_time
            ):
                await conn.close()
                if conn in self.connections:
                    self.connections.remove(conn)
                
                # FIX: Immediately try to get a replacement instead of looping/waiting
                # If we can create a new one, do it now
                async with self.lock:
                    if len(self.connections) < self.pool_size:
                        conn = AsyncSMTPConnection(self.config)
                        await conn.connect()
                        self.connections.append(conn)
                    else:
                        # Pool is full but we just discarded one? 
                        # Race condition handled by loop
                        return await self.get_connection(timeout)
            
            return conn
            
        except asyncio.TimeoutError:
            # Create new connection if pool allows
            async with self.lock:
                if len(self.connections) < self.pool_size:
                    conn = AsyncSMTPConnection(self.config)
                    await conn.connect()
                    self.connections.append(conn)
                    return conn
            
            # Wait for available connection
            return await asyncio.wait_for(self.available.get(), timeout=timeout/2)
    
    async def release_connection(self, conn: AsyncSMTPConnection):
        """Return connection to pool."""
        if (
            conn.is_connected
            and conn.age_seconds < self.max_connection_age
            and conn.idle_seconds < self.max_idle_time
        ):
            await self.available.put(conn)
            return
        
        await conn.close()
        async with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)
        
        # FIX: Proactively replenish to wake up waiters
        asyncio.create_task(self._replenish_one())
    
    # Backward-compatible alias expected by tests
    async def return_connection(self, conn: AsyncSMTPConnection):
        await self.release_connection(conn)
    
    async def close_all(self):
        """Close all connections."""
        async with self.lock:
            for conn in self.connections:
                await conn.close()
            self.connections.clear()
            self._initialized = False


class SMTPConnectionPool:
    """Multi-server SMTP connection pool with load balancing."""
    
    def __init__(
        self,
        configs: List[SMTPServerConfig],
        pool_size_per_server: int = 5,
        selection_strategy: str = 'round_robin'
    ):
        self.configs = configs
        self.pools: Dict[str, AsyncConnectionPool] = {}
        # Backward-compatible alias expected by tests
        self._pools = self.pools
        # Default to round-robin for deterministic selection in tests
        self.selection_strategy = selection_strategy or 'round_robin'
        self.lock = asyncio.Lock()
        self._round_robin_index = 0
        
        # Create pools for each server
        for config in configs:
            self.pools[config.name] = AsyncConnectionPool(
                config, 
                pool_size=pool_size_per_server
            )
    
    def _select_server_weighted(self) -> Optional[SMTPServerConfig]:
        """Select server using weighted random selection."""
        import random
        
        available = [
            c for c in self.configs 
            if c.can_execute()
        ]
        
        if not available:
            return None
        
        total_weight = sum(c.weight for c in available)
        if total_weight <= 0:
            return random.choice(available)
        
        r = random.uniform(0, total_weight)
        cumulative = 0
        for config in available:
            cumulative += config.weight
            if r <= cumulative:
                return config
        
        return available[-1]
    
    def _select_server_round_robin(self) -> Optional[SMTPServerConfig]:
        """Select server using round-robin."""
        available = [
            c for c in self.configs 
            if c.can_execute()
        ]
        
        if not available:
            return None
        
        config = available[self._round_robin_index % len(available)]
        self._round_robin_index += 1
        return config
    
    def _select_server_priority(self) -> Optional[SMTPServerConfig]:
        """Select server by priority."""
        available = [
            c for c in self.configs 
            if c.can_execute()
        ]
        
        if not available:
            return None
        
        # Sort by priority (higher is better)
        available.sort(key=lambda c: c.priority, reverse=True)
        return available[0]
    
    def select_server(self) -> Optional[SMTPServerConfig]:
        """Select best available server."""
        if self.selection_strategy == 'weighted':
            return self._select_server_weighted()
        elif self.selection_strategy == 'round_robin':
            return self._select_server_round_robin()
        elif self.selection_strategy == 'priority':
            return self._select_server_priority()
        else:
            return self._select_server_weighted()
    
    async def acquire(
        self, 
        preferred_server: str = None,
        timeout: float = 10.0
    ) -> Tuple[AsyncSMTPConnection, SMTPServerConfig]:
        """Acquire connection from pool."""
        # Try preferred server first
        if preferred_server and preferred_server in self.pools:
            config = next((c for c in self.configs if c.name == preferred_server), None)
            if config and config.can_execute():
                pool = self.pools[preferred_server]
                conn = await pool.get_connection(timeout)
                return conn, config
        
        # Select server using strategy
        config = self.select_server()
        if not config:
            raise RuntimeError("No SMTP servers available")
        
        pool = self.pools[config.name]
        conn = await pool.get_connection(timeout)
        return conn, config
    
    async def release(self, conn: AsyncSMTPConnection, config: SMTPServerConfig):
        """Release connection back to pool."""
        if config.name in self.pools:
            await self.pools[config.name].release_connection(conn)
    
    def record_success(self, config: SMTPServerConfig):
        """Record successful send."""
        config.circuit_breaker.record_success()
        config.total_sent += 1
        config.consecutive_failures = 0
    
    def record_failure(self, config: SMTPServerConfig, error: Exception):
        """Record failed send."""
        config.circuit_breaker.record_failure(error)
        config.total_failures += 1
        config.consecutive_failures += 1
        
        # Check for rate limiting
        error_str = str(error).lower()
        if any(kw in error_str for kw in ['rate', 'throttle', 'too many', '421', '450']):
            logger.warning(f"Rate limiting detected on {config.name}")
    
    async def close_all(self):
        """Close all pools."""
        for pool in self.pools.values():
            await pool.close_all()
    
    def get_status(self) -> Dict[str, Any]:
        """Get pool status keyed by server name."""
        status = {}
        for c in self.configs:
            stats = c.circuit_breaker.get_stats()
            status[c.name] = {
                'host': c.host,
                'circuit_state': stats['state'],
                'minute_count': c.current_minute_count,
                'hour_count': c.current_hour_count,
                'available': c.can_execute(),
                'total_sent': c.total_sent,
                'consecutive_failures': c.consecutive_failures,
                'total_failures': c.total_failures,
            }
        return status

