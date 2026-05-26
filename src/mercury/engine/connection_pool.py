"""SMTP connection pooling with circuit breaker and load balancing."""

import asyncio
import logging
import threading
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, UTC
from dataclasses import dataclass, field
import aiosmtplib

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig

logger = logging.getLogger(__name__)


class ConnectionPoolException(Exception):
    """Errors related to connection pool operations."""
    pass


def _create_circuit_breaker(
    server_name: str = "default",
    *,
    failure_threshold: int = 5,
    success_threshold: int = 3,
    timeout_seconds: int = 60,
    monitor_window_seconds: int = 300,
) -> CircuitBreaker:
    """Factory function to create a circuit breaker.

    Defaults match the previous hard-coded values; per-server overrides flow
    in through ``SMTPServerConfig`` fields and ultimately ``from_dict``.
    """
    return CircuitBreaker(
        server_name=server_name,
        config=CircuitBreakerConfig(
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            timeout_seconds=timeout_seconds,
            monitor_window_seconds=monitor_window_seconds,
        ),
    )


@dataclass
class SMTPServerRuntime:
    """Per-process mutable runtime state for an SMTP server.

    Separated from ``SMTPServerConfig`` so the config itself can stay
    immutable / hashable / cacheable, and so it's obvious what state lives
    only in this worker's memory (vs. what's persisted in the DB).

    Counters here intentionally do NOT round-trip to the database — the
    earlier ``current_minute_count`` / ``current_hour_count`` columns were
    dropped in migration ``d7a2f8e4b9c1`` because each worker maintains its
    own independent counter and persisting one-of-many is meaningless.
    """
    circuit_breaker: CircuitBreaker
    current_minute_count: int = 0
    current_hour_count: int = 0
    total_sent: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_minute_reset: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_hour_reset: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SMTPServerConfig:
    """SMTP server configuration.

    Static configuration only — connection details, rate-limit *caps*, and
    circuit-breaker tuning. Mutable per-process counters live on the
    ``runtime`` companion (see ``SMTPServerRuntime``).
    """
    name: str
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    # 'none' | 'starttls' | 'ssl' — single source of truth for TLS.
    tls_mode: str = 'starttls'
    use_auth: bool = True
    timeout: int = 30
    from_email: str = ""
    from_name: str = ""
    weight: float = 1.0
    priority: int = 0
    max_per_minute: int = 30
    max_per_hour: int = 500

    # Circuit breaker tuning (per-server overrides; None = use defaults).
    cb_failure_threshold: Optional[int] = None
    cb_success_threshold: Optional[int] = None
    cb_timeout_seconds: Optional[int] = None
    cb_monitor_window_seconds: Optional[int] = None

    # Mutable runtime state — initialized in __post_init__ so callers don't
    # have to construct it explicitly.
    runtime: SMTPServerRuntime = field(default=None)

    def __post_init__(self):
        """Initialize the runtime companion (circuit breaker + counters)."""
        if self.runtime is None:
            cb_kwargs = {}
            if self.cb_failure_threshold is not None:
                cb_kwargs['failure_threshold'] = self.cb_failure_threshold
            if self.cb_success_threshold is not None:
                cb_kwargs['success_threshold'] = self.cb_success_threshold
            if self.cb_timeout_seconds is not None:
                cb_kwargs['timeout_seconds'] = self.cb_timeout_seconds
            if self.cb_monitor_window_seconds is not None:
                cb_kwargs['monitor_window_seconds'] = self.cb_monitor_window_seconds
            self.runtime = SMTPServerRuntime(
                circuit_breaker=_create_circuit_breaker(self.name, **cb_kwargs),
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SMTPServerConfig':
        """Create config from dictionary."""
        # tls_mode is the single TLS field. Missing → defaults to 'starttls'
        # (the product default for port 587). Legacy use_tls / use_ssl
        # booleans are no longer derived from; a config that supplied them
        # without tls_mode used to be honored and is now treated as defaulted.
        raw = data.get('tls_mode')
        if raw is None:
            tls_mode = 'starttls'
        else:
            tls_mode = str(raw).strip().lower()
            if tls_mode not in ('none', 'starttls', 'ssl'):
                raise ValueError(
                    f"SMTPServerConfig.from_dict: 'tls_mode' must be one of "
                    f"'none', 'starttls', 'ssl' (got: {raw!r})"
                )
        return cls(
            name=data.get('name', data.get('host', 'default')),
            host=data['host'],
            port=data.get('port', 587),
            username=data.get('username', ''),
            password=data.get('password', ''),
            tls_mode=tls_mode,
            use_auth=data.get('use_auth', True),
            timeout=data.get('timeout', 30),
            from_email=data.get('from_email', ''),
            from_name=data.get('from_name', ''),
            weight=data.get('weight', 1.0),
            priority=data.get('priority', 0),
            max_per_minute=data.get('max_per_minute', 30),
            max_per_hour=data.get('max_per_hour', 500),
            cb_failure_threshold=data.get('cb_failure_threshold'),
            cb_success_threshold=data.get('cb_success_threshold'),
            cb_timeout_seconds=data.get('cb_timeout_seconds'),
            cb_monitor_window_seconds=data.get('cb_monitor_window_seconds'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'tls_mode': self.tls_mode,
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
        rt = self.runtime

        # Reset minute counter
        if (now - rt.last_minute_reset).total_seconds() >= 60:
            rt.current_minute_count = 0
            rt.last_minute_reset = now

        # Reset hour counter
        if (now - rt.last_hour_reset).total_seconds() >= 3600:
            rt.current_hour_count = 0
            rt.last_hour_reset = now

        return (
            rt.current_minute_count < self.max_per_minute and
            rt.current_hour_count < self.max_per_hour
        )

    def increment_counters(self):
        """Increment rate limit counters."""
        rt = self.runtime
        rt.current_minute_count += 1
        rt.current_hour_count += 1

    def can_execute(self) -> bool:
        """Check if server can accept requests (circuit breaker + rate limits)."""
        return self.runtime.circuit_breaker.is_available() and self.check_rate_limits()


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
        """Establish async SMTP connection. Dispatches on ``tls_mode``."""
        mode = self.config.tls_mode
        implicit_tls = (mode == 'ssl')

        self.client = aiosmtplib.SMTP(
            hostname=self.config.host,
            port=self.config.port,
            use_tls=implicit_tls,
            timeout=self.config.timeout
        )

        await self.client.connect()

        if mode == 'starttls':
            await self.client.starttls()

        if self.config.use_auth and self.config.username:
            await self.client.login(self.config.username, self.config.password)

        self.is_connected = True
        logger.debug(
            f"Connected to {self.config.name} "
            f"({self.config.host}:{self.config.port}, tls_mode={mode})"
        )
    
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
            
            last_exc: Optional[Exception] = None
            for _ in range(min(2, self.pool_size)):  # Start with 2 connections
                try:
                    conn = AsyncSMTPConnection(self.config)
                    await conn.connect()
                    self.connections.append(conn)
                    await self.available.put(conn)
                except Exception as e:
                    last_exc = e
                    logger.warning(f"Failed to create initial connection: {e}")
            
            self._initialized = True

            # All warm connections failed — fail fast so the caller (campaign runner)
            # sees the real error immediately instead of spawning hundreds of doomed
            # send tasks that each silently fail with the same error.
            if last_exc is not None and not self.connections:
                self._initialized = False  # allow retry once credentials are fixed
                raise last_exc
    
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
    
    async def close_all(self):
        """Close all connections."""
        async with self.lock:
            for conn in self.connections:
                await conn.close()
            self.connections.clear()
            self._initialized = False


# Process-wide registry of live SMTPConnectionPool instances. Used to
# propagate SMTP config edits (credential rotations, TLS-mode changes)
# into running campaigns — without this, a PUT /api/smtp/<name> only
# updates the DB row while in-flight pools keep authenticating with the
# old password. Registered in __init__; unregistered in close_all.
#
# The lock guards every mutation/read. Necessary because pools can be
# created on the campaign event-loop thread while close_all may run on
# a different thread (Flask request handler invalidating a server, or
# the shared background loop tearing things down at shutdown). list()
# is atomic in CPython but is not a guarantee we want to rely on under
# the eventlet + threading + asyncio mix this codebase tolerates.
_ACTIVE_POOLS: "list[SMTPConnectionPool]" = []
_ACTIVE_POOLS_LOCK = threading.Lock()


def iter_active_pools() -> "list[SMTPConnectionPool]":
    """Snapshot the active-pool registry for callers that want to iterate
    safely while pools may register/unregister concurrently."""
    with _ACTIVE_POOLS_LOCK:
        return list(_ACTIVE_POOLS)


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
        # Default to round-robin for deterministic selection in tests
        self.selection_strategy = selection_strategy or 'round_robin'
        self.lock = asyncio.Lock()
        self._round_robin_index = 0
        self._pool_size_per_server = pool_size_per_server

        # Create pools for each server
        for config in configs:
            self.pools[config.name] = AsyncConnectionPool(
                config,
                pool_size=pool_size_per_server
            )

        with _ACTIVE_POOLS_LOCK:
            _ACTIVE_POOLS.append(self)

    async def invalidate_server(self, name: str, new_config: Optional[SMTPServerConfig] = None) -> bool:
        """Refresh a single server's connections after a config update.

        Closes the existing pool (which forces all subsequent acquires to
        open new connections that pick up the latest credentials / TLS
        mode / host / port), and replaces the SMTPServerConfig entry if
        ``new_config`` is supplied. Returns True if the named server was
        found in this pool, False otherwise.

        Safe to call while sends are in flight: ongoing aiosmtplib calls
        on already-acquired connections complete on the original auth
        session; only newly-acquired connections see the updated config.
        """
        if name not in self.pools:
            return False

        # Replace config first so any concurrent acquire() that hits the
        # newly-created pool reads the fresh credentials.
        if new_config is not None:
            self.configs = [
                (new_config if c.name == name else c) for c in self.configs
            ]
            
            # If the server was renamed, we need to map the new pool to the new name,
            # and clean up the old name key.
            if new_config.name != name:
                self.pools[new_config.name] = AsyncConnectionPool(
                    new_config,
                    pool_size=self._pool_size_per_server,
                )
                old_pool = self.pools.pop(name, None)
                if old_pool:
                    try:
                        import asyncio
                        # We don't await here directly since invalidate_server is called safely 
                        # but just to be safe, close it asynchronously.
                        # Wait, we are in an async function.
                        await old_pool.close_all()
                    except Exception as e:
                        logger.warning(f"close_all error for {name} during invalidate: {e}")
            else:
                self.pools[name] = AsyncConnectionPool(
                    new_config,
                    pool_size=self._pool_size_per_server,
                )

        # Close out the old pool (or the just-replaced one if no
        # new_config was passed — operator wanted a force-reset).
        # We only do this if it wasn't a rename (rename cleanup happens above).
        if name in self.pools:
            try:
                await self.pools[name].close_all() if new_config is None else None
            except Exception as e:
                logger.warning(f"close_all error for {name} during invalidate: {e}")
        logger.info(f"Invalidated pool for SMTP server '{name}'")
        return True
    
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

    def select_server_for_from(self, from_email: str) -> Optional[SMTPServerConfig]:
        """Pick a healthy server that declares ownership of ``from_email``.

        Each SMTPServerConfig.from_email declares the address that server
        is authorized to send as on the upstream relay. When a campaign
        rotates From across multiple addresses, routing each From through
        a server that *owns* it prevents the gateway-side 5.7.0 "From not
        in your addresses" rejection that O365, SES, and SendGrid emit
        for header/auth mismatches.

        Returns None when no enabled server owns ``from_email`` — the
        caller decides whether to fail loud (preferred) or fall back to
        plain rotation. Silent fallback here would mask exactly the bug
        this method exists to prevent.

        Multiple servers can legitimately own the same address (HA pairs,
        warm pools). When that happens, the normal selection strategy
        (weighted / round-robin / priority) rotates among the owners so
        weight and circuit-breaker health still matter.
        """
        if not from_email:
            return None
        target = from_email.strip().lower()
        owners = [
            c for c in self.configs
            if c.can_execute() and (c.from_email or '').strip().lower() == target
        ]
        if not owners:
            return None
        if len(owners) == 1:
            return owners[0]
        # Multiple owners — apply normal strategy among them. We do this by
        # temporarily masking self.configs; cleaner than duplicating each
        # strategy with a candidate-list parameter.
        original_configs = self.configs
        try:
            self.configs = owners
            return self.select_server()
        finally:
            self.configs = original_configs
    
    async def acquire(
        self,
        preferred_server: str = None,
        timeout: float = 10.0
    ) -> Tuple[AsyncSMTPConnection, SMTPServerConfig]:
        """Acquire connection from pool.

        A non-None ``preferred_server`` is authoritative: it supersedes the
        configured selection strategy. If the named server is unknown or
        currently unable to execute (rate-limited / circuit open), this
        raises rather than silently falling back to rotation — falling back
        would let the caller's mail leave on a server it didn't pin, which
        breaks SMTP-auth-bound From-address policies on relays that enforce
        ``smtpd_sender_login_maps``-style rules.
        """
        if preferred_server:
            if preferred_server not in self.pools:
                raise RuntimeError(
                    f"Preferred SMTP server '{preferred_server}' is not configured"
                )
            config = next((c for c in self.configs if c.name == preferred_server), None)
            if not config:
                raise RuntimeError(
                    f"Preferred SMTP server '{preferred_server}' has no config"
                )
            if not config.can_execute():
                raise RuntimeError(
                    f"Preferred SMTP server '{preferred_server}' is unavailable "
                    f"(rate-limited or circuit open)"
                )
            conn = await self.pools[preferred_server].get_connection(timeout)
            return conn, config

        config = self.select_server()
        if not config:
            # Surface the most recent real failure from each tripped
            # circuit breaker. Previously this raised a bare "No SMTP
            # servers available" which became the user-facing error for
            # every subsequent cascading recipient — hiding the actual
            # cause (e.g. iCloud's 5.7.0 "From address is not one of
            # your addresses"). With this, the cascade error includes
            # the root cause so the operator doesn't need to dig
            # through per-recipient logs.
            details = []
            for c in self.configs:
                try:
                    cb_stats = c.runtime.circuit_breaker.get_stats()
                    if cb_stats.get('state') == 'open':
                        msgs = cb_stats.get('last_error_messages') or []
                        last = msgs[-1] if msgs else 'unknown'
                        details.append(f"{c.name}: circuit open — last error: {last}")
                except Exception:
                    pass
            if details:
                raise RuntimeError(
                    "All SMTP servers' circuit breakers are open. "
                    + " | ".join(details)
                )
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
        rt = config.runtime
        rt.circuit_breaker.record_success()
        rt.total_sent += 1
        rt.consecutive_failures = 0

    def record_failure(self, config: SMTPServerConfig, error: Exception):
        """Record failed send."""
        rt = config.runtime
        rt.circuit_breaker.record_failure(error)
        rt.total_failures += 1
        rt.consecutive_failures += 1
        
        # Check for rate limiting
        error_str = str(error).lower()
        if any(kw in error_str for kw in ['rate', 'throttle', 'too many', '421', '450']):
            logger.warning(f"Rate limiting detected on {config.name}")
    
    async def close_all(self):
        """Close all pools."""
        for pool in self.pools.values():
            await pool.close_all()
        with _ACTIVE_POOLS_LOCK:
            try:
                _ACTIVE_POOLS.remove(self)
            except ValueError:
                pass

    def get_status(self) -> Dict[str, Any]:
        """Get pool status keyed by server name."""
        status = {}
        for c in self.configs:
            rt = c.runtime
            stats = rt.circuit_breaker.get_stats()
            status[c.name] = {
                'host': c.host,
                'circuit_state': stats['state'],
                'minute_count': rt.current_minute_count,
                'hour_count': rt.current_hour_count,
                'available': c.can_execute(),
                'total_sent': rt.total_sent,
                'consecutive_failures': rt.consecutive_failures,
                'total_failures': rt.total_failures,
            }
        return status

