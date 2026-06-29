"""SMTP connection pooling with circuit breaker and load balancing."""

import asyncio
import logging
import threading
import time
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, UTC
from dataclasses import dataclass, field
import aiosmtplib

from .circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from ..exceptions import SMTPRateLimitError

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
    handshake_latencies: List[float] = field(default_factory=list)
    send_latencies: List[float] = field(default_factory=list)

    @property
    def avg_handshake_latency(self) -> Optional[float]:
        """Get average connection handshake latency in seconds."""
        if not self.handshake_latencies:
            return None
        return sum(self.handshake_latencies) / len(self.handshake_latencies)

    @property
    def avg_send_latency(self) -> Optional[float]:
        """Get average mail sending latency in seconds."""
        if not self.send_latencies:
            return None
        return sum(self.send_latencies) / len(self.send_latencies)

    def record_handshake(self, seconds: float) -> None:
        """Record a connection handshake latency measurement."""
        self.handshake_latencies.append(seconds)
        if len(self.handshake_latencies) > 50:
            self.handshake_latencies.pop(0)

    def record_handshake_latency(self, seconds: float) -> None:
        """Record a connection handshake latency measurement."""
        self.record_handshake(seconds)

    def record_send(self, seconds: float) -> None:
        """Record a mail sending latency measurement."""
        self.send_latencies.append(seconds)
        if len(self.send_latencies) > 50:
            self.send_latencies.pop(0)

    def record_send_latency(self, seconds: float) -> None:
        """Record a mail sending latency measurement."""
        self.record_send(seconds)


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
    tls_mode: str = "starttls"
    use_auth: bool = True
    timeout: int = 30
    from_email: str = ""
    from_name: str = ""
    weight: float = 1.0
    priority: int = 0
    max_per_minute: int = 30
    max_per_hour: int = 500

    # IP Warmup
    total_sent_historical: int = 0
    created_at_timestamp: float = 0.0

    # Circuit breaker tuning (per-server overrides; None = use defaults).
    cb_failure_threshold: Optional[int] = None
    cb_success_threshold: Optional[int] = None
    cb_timeout_seconds: Optional[int] = None
    cb_monitor_window_seconds: Optional[int] = None

    # Mutable runtime state — initialized in __post_init__ so callers don't
    # have to construct it explicitly.
    runtime: Optional[SMTPServerRuntime] = field(default=None)

    def __post_init__(self):
        """Initialize the runtime companion (circuit breaker + counters)."""
        if self.runtime is None:
            cb_kwargs = {}
            if self.cb_failure_threshold is not None:
                cb_kwargs["failure_threshold"] = self.cb_failure_threshold
            if self.cb_success_threshold is not None:
                cb_kwargs["success_threshold"] = self.cb_success_threshold
            if self.cb_timeout_seconds is not None:
                cb_kwargs["timeout_seconds"] = self.cb_timeout_seconds
            if self.cb_monitor_window_seconds is not None:
                cb_kwargs["monitor_window_seconds"] = self.cb_monitor_window_seconds
            self.runtime = SMTPServerRuntime(
                circuit_breaker=_create_circuit_breaker(self.name, **cb_kwargs),
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SMTPServerConfig":
        """Create config from dictionary."""
        # tls_mode is the single TLS field. Missing → defaults to 'starttls'
        # (the product default for port 587). Legacy use_tls / use_ssl
        # booleans are no longer derived from; a config that supplied them
        # without tls_mode used to be honored and is now treated as defaulted.
        raw = data.get("tls_mode")
        if raw is None:
            tls_mode = "starttls"
        else:
            tls_mode = str(raw).strip().lower()
            if tls_mode not in ("none", "starttls", "ssl"):
                raise ValueError(
                    f"SMTPServerConfig.from_dict: 'tls_mode' must be one of "
                    f"'none', 'starttls', 'ssl' (got: {raw!r})"
                )
        return cls(
            name=str(data.get("name", data.get("host", "default"))),
            host=data["host"],
            port=data.get("port", 587),
            username=data.get("username", ""),
            password=data.get("password", ""),
            tls_mode=tls_mode,
            use_auth=data.get("use_auth", True),
            timeout=data.get("timeout", 30),
            from_email=data.get("from_email", ""),
            from_name=data.get("from_name", ""),
            weight=data.get("weight", 1.0),
            priority=data.get("priority", 0),
            max_per_minute=data.get("max_per_minute", 30),
            max_per_hour=data.get("max_per_hour", 500),
            total_sent_historical=data.get("total_sent_historical", 0),
            created_at_timestamp=data.get("created_at_timestamp", 0.0),
            cb_failure_threshold=data.get("cb_failure_threshold"),
            cb_success_threshold=data.get("cb_success_threshold"),
            cb_timeout_seconds=data.get("cb_timeout_seconds"),
            cb_monitor_window_seconds=data.get("cb_monitor_window_seconds"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "tls_mode": self.tls_mode,
            "use_auth": self.use_auth,
            "timeout": self.timeout,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "weight": self.weight,
            "priority": self.priority,
            "max_per_minute": self.max_per_minute,
            "max_per_hour": self.max_per_hour,
            "total_sent_historical": self.total_sent_historical,
            "created_at_timestamp": self.created_at_timestamp,
        }

    def check_rate_limits(self, ip_warmup_mode: bool = False) -> bool:
        """Check if within rate limits."""
        rt = self.runtime
        assert rt is not None, "SMTPServerRuntime not initialized"
        now = datetime.now(UTC)

        effective_max_minute = self.max_per_minute
        effective_max_hour = self.max_per_hour

        # IP Warm-up pacing dynamically based on domain age / sent quotas
        if ip_warmup_mode and self.created_at_timestamp > 0:
            created_at = datetime.fromtimestamp(self.created_at_timestamp, tz=UTC)
            age_days = (now - created_at).days
            total = self.total_sent_historical + rt.total_sent

            if age_days <= 1 or total <= 50:
                effective_max_minute = min(effective_max_minute, 2)
                effective_max_hour = min(effective_max_hour, 10)
            elif age_days <= 3 or total <= 200:
                effective_max_minute = min(effective_max_minute, 5)
                effective_max_hour = min(effective_max_hour, 50)
            elif age_days <= 7 or total <= 1000:
                effective_max_minute = min(effective_max_minute, 10)
                effective_max_hour = min(effective_max_hour, 200)

        # Reset minute counter
        if (now - rt.last_minute_reset).total_seconds() >= 60:
            rt.current_minute_count = 0
            rt.last_minute_reset = now

        # Reset hour counter
        if (now - rt.last_hour_reset).total_seconds() >= 3600:
            rt.current_hour_count = 0
            rt.last_hour_reset = now

        return (
            rt.current_minute_count < effective_max_minute
            and rt.current_hour_count < effective_max_hour
        )

    def increment_counters(self):
        """Increment rate limit counters."""
        rt = self.runtime
        assert rt is not None, "SMTPServerRuntime not initialized"
        rt.current_minute_count += 1
        rt.current_hour_count += 1

    def can_execute(self, ip_warmup_mode: bool = False) -> bool:
        """Check if server can accept requests (circuit breaker + rate limits)."""
        if self.runtime is None:
            return False
        return self.runtime.circuit_breaker.is_available() and self.check_rate_limits(
            ip_warmup_mode
        )


class AsyncSMTPConnection:
    """Async SMTP connection wrapper."""

    def __init__(self, config: SMTPServerConfig):
        self.config = config
        self.client: Optional[aiosmtplib.SMTP] = None
        self.is_connected = False
        self.created_at = datetime.now(UTC)
        self.last_used = datetime.now(UTC)
        self.messages_sent = 0

    # Ports where plaintext SMTP is almost always misconfiguration: 587 is
    # submission (RFC 4409 — STARTTLS expected), 465 is implicit-TLS
    # submission, 2525 is the unofficial-but-conventional alt-submission.
    # If we see tls_mode='none' on one of these, the user almost certainly
    # picked the wrong dropdown value OR was bitten by the use_tls=0
    # migration backfill in 20260515_0001_a1c5d9e3f721 — which faithfully
    # translated legacy use_tls=0 to tls_mode='none' for pre-existing rows
    # that should've been STARTTLS. Either way, mail goes out plaintext
    # (or auth gets rejected outright), the relay accepts/rejects with
    # whatever code it wants, and the operator wonders why nothing's
    # delivering. Loud once-per-connect log so the cause is obvious.
    _TLS_EXPECTED_PORTS = (465, 587, 2525)

    async def connect(self) -> None:
        """Establish async SMTP connection. Dispatches on ``tls_mode``."""
        _start = time.monotonic()
        mode = self.config.tls_mode
        implicit_tls = mode == "ssl"

        if mode == "none" and self.config.port in self._TLS_EXPECTED_PORTS:
            logger.warning(
                "⚠️  SMTP server %s configured with tls_mode='none' on port %d "
                "(submission port — STARTTLS or implicit TLS is expected). "
                "Plaintext AUTH will likely be rejected and any mail that DOES "
                "go out is unencrypted. Set tls_mode='starttls' (587/2525) or "
                "'ssl' (465) in the SMTP form to fix.",
                self.config.name,
                self.config.port,
            )

        self.client = aiosmtplib.SMTP(
            hostname=self.config.host,
            port=self.config.port,
            use_tls=implicit_tls,
            timeout=self.config.timeout,
        )

        await self.client.connect()

        if mode == "starttls":
            await self.client.starttls()

        if self.config.use_auth and self.config.username:
            await self.client.login(self.config.username, self.config.password)

        self.is_connected = True
        _duration = time.monotonic() - _start
        if self.config.runtime is not None:
            self.config.runtime.record_handshake(_duration)

        logger.debug(
            f"Connected to {self.config.name} "
            f"({self.config.host}:{self.config.port}, tls_mode={mode}) in {_duration:.3f}s"
        )

    async def send_message(self, msg) -> Dict[str, Any]:
        """Send email message."""
        if not self.is_connected or not self.client:
            await self.connect()

        _start = time.monotonic()
        assert self.client is not None
        try:
            response = await self.client.send_message(msg)
            _duration = time.monotonic() - _start
            if self.config.runtime is not None:
                self.config.runtime.record_send(_duration)

            self.last_used = datetime.now(UTC)
            self.messages_sent += 1
            self.config.increment_counters()
            return {"success": True, "response": str(response)}
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

    async def is_alive(self, timeout: float = 5.0) -> bool:
        """Liveness probe: NOOP the server to confirm it still responds.

        ``is_connected`` is only a *local* flag — it stays True after a
        server (or an intervening NAT / firewall / load balancer) silently
        drops an idle TCP connection. Reusing such a half-open connection
        means the next real command (MAIL FROM) lands in a dead socket and
        the server "doesn't respond". A cheap NOOP catches that *before* we
        commit a message; on any failure we mark the connection dead so the
        pool discards it. The ``wait_for`` guard bounds the half-open case
        where the FIN was lost and the response read would otherwise block.
        """
        if not self.is_connected or not self.client:
            return False
        try:
            await asyncio.wait_for(self.client.noop(), timeout=timeout)
            return True
        except Exception:
            self.is_connected = False
            return False

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
        max_idle_time: float = 60.0,
        pre_ping_idle_threshold: float = 5.0,
    ):
        self.config = config
        self.pool_size = pool_size
        self.max_connection_age = max_connection_age
        self.max_idle_time = max_idle_time
        # A connection idle longer than this gets a NOOP liveness probe on
        # checkout (see _is_reusable). Kept small so any realistically-stale
        # connection is caught, while back-to-back reuse in a tight send
        # loop (idle well under the window) skips the round-trip.
        self.pre_ping_idle_threshold = pre_ping_idle_threshold

        self.connections: List[AsyncSMTPConnection] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self.lock = asyncio.Lock()
        self._initialized = False
        # Strong refs to fire-and-forget replenish tasks. Without this the
        # only reference to the Task is the event loop's weak one, and CPython
        # will happily GC a still-pending task — producing "Task was destroyed
        # but it is pending!" warnings and silently dropping the replenish.
        self._background_tasks: "set[asyncio.Task]" = set()
        self._waiters: "list[tuple[int, int, asyncio.Future]]" = []
        self._waiter_counter = 0

    async def initialize(self):
        """Initialize the pool with connections."""
        if self._initialized:
            return

        async with self.lock:
            if self._initialized:
                return

            last_exc: Optional[Exception] = None
            # Seed the full pool. The previous min(2, pool_size) cap meant
            # a campaign with concurrency=50 and pool_size_per_server=10
            # opened only 2 warm connections — the first ~48 sends all
            # serialized on the get_connection queue-wait race, defeating
            # the pool's whole purpose. Failures during seeding are still
            # tolerated individually below; we only fail-fast if EVERY
            # connection attempt fails (handled after the loop).
            for _ in range(self.pool_size):
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

                # Clean up done/cancelled waiters
                self._waiters = [w for w in self._waiters if not w[2].done()]
                if self._waiters:
                    self._waiters.sort(key=lambda x: (x[0], x[1]))
                    priority, counter, future = self._waiters.pop(0)
                    future.set_result(conn)
                else:
                    await self.available.put(conn)
                logger.debug(f"Replenished connection pool for {self.config.name}")
            except Exception as e:
                logger.warning(f"Failed to replenish connection: {e}")
                # Don't raise, we'll try again later naturally

    async def _discard(self, conn: AsyncSMTPConnection) -> None:
        """Close a connection and drop it from the pool's tracking list."""
        await conn.close()
        async with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)

    async def _is_reusable(self, conn: AsyncSMTPConnection) -> bool:
        """Decide whether a pooled connection is safe to hand out.

        Returns True if the caller may use ``conn``. Returns False (and has
        already discarded it) if it is too old, too long idle, or fails a
        liveness probe — the caller should then continue the acquire loop to
        get or open another. The NOOP pre-ping (only for connections idle
        past ``pre_ping_idle_threshold``) is what prevents a server-side or
        middlebox-closed half-open connection from being used for a real
        send and surfacing as "SMTP server not responding to commands".
        """
        if (
            not conn.is_connected
            or conn.age_seconds > self.max_connection_age
            or conn.idle_seconds > self.max_idle_time
        ):
            await self._discard(conn)
            return False

        if conn.idle_seconds > self.pre_ping_idle_threshold and not await conn.is_alive():
            await self._discard(conn)
            return False

        return True

    async def get_connection(self, timeout: float = 10.0, priority: int = 2) -> AsyncSMTPConnection:
        """Get a connection from the pool, with priority queuing.

        Operates against a single deadline computed at entry. The previous
        implementation recursed with the same ``timeout`` on stale-replace
        races, which produced two problems: (1) the effective wait halved
        on every recursion (``timeout/2`` per branch) so a caller asking
        for 30s could quietly get 7.5s after two recursions, and (2) under
        sustained churn the recursion depth grew unbounded. This loop
        spends *real* time against ``deadline`` and rotates between
        "wait for an existing conn" and "open a new one when pool has
        room" until one path succeeds or the deadline expires.
        """
        await self.initialize()

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        def _remaining() -> float:
            return max(0.0, deadline - loop.time())

        while True:
            remaining = _remaining()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"get_connection timed out for {self.config.name} after {timeout:.1f}s"
                )

            conn = None
            async with self.lock:
                self._waiters = [w for w in self._waiters if not w[2].done()]
                has_higher_priority_waiter = any(w[0] < priority for w in self._waiters)
                if not self.available.empty() and not has_higher_priority_waiter:
                    conn = self.available.get_nowait()

            if conn is not None:
                # Validate (and liveness-probe) before handing out. Continuing
                # the loop rather than recursing preserves the original
                # deadline, so a flurry of stale conns can't shrink the
                # effective timeout.
                if not await self._is_reusable(conn):
                    continue
                return conn

            # No conn appeared in time — try to open a new one if there's
            # room. Holding the lock across connect() is unavoidable: we
            # need the slot count to be consistent with the slot we're
            # filling. SMTP connect on a healthy server is fast (<300ms);
            # if the relay is slow, the deadline check above will eventually
            # bail out.
            async with self.lock:
                if len(self.connections) < self.pool_size:
                    conn = AsyncSMTPConnection(self.config)
                    try:
                        await conn.connect()
                    except Exception:
                        # Don't keep a half-open record in the pool.
                        raise
                    self.connections.append(conn)
                    return conn

            # Pool is full — wait for a connection to be released with priority.
            future = loop.create_future()
            async with self.lock:
                self._waiter_counter += 1
                waiter_item = (priority, self._waiter_counter, future)
                self._waiters.append(waiter_item)

            try:
                acquired = await asyncio.wait_for(future, timeout=remaining)
                if not await self._is_reusable(acquired):
                    continue
                return acquired
            except asyncio.TimeoutError:
                future.cancel()
                async with self.lock:
                    if waiter_item in self._waiters:
                        self._waiters.remove(waiter_item)
                raise asyncio.TimeoutError(
                    f"get_connection timed out for {self.config.name} after {timeout:.1f}s"
                )

    async def release_connection(self, conn: AsyncSMTPConnection):
        """Return connection to pool."""
        if (
            conn.is_connected
            and conn.age_seconds < self.max_connection_age
            and conn.idle_seconds < self.max_idle_time
        ):
            async with self.lock:
                # Clean up done/cancelled waiters
                self._waiters = [w for w in self._waiters if not w[2].done()]
                if self._waiters:
                    self._waiters.sort(key=lambda x: (x[0], x[1]))
                    priority, counter, future = self._waiters.pop(0)
                    future.set_result(conn)
                    return
            await self.available.put(conn)
            return

        await conn.close()
        async with self.lock:
            if conn in self.connections:
                self.connections.remove(conn)

        # FIX: Proactively replenish to wake up waiters
        task = asyncio.create_task(self._replenish_one())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

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
        selection_strategy: str = "round_robin",
        ip_warmup_mode: bool = False,
    ):
        self.configs = configs
        self.pools: Dict[str, AsyncConnectionPool] = {}
        # Default to round-robin for deterministic selection in tests
        self.selection_strategy = selection_strategy or "round_robin"
        self.ip_warmup_mode = ip_warmup_mode
        self.lock = asyncio.Lock()
        self._round_robin_index = 0
        self._pool_size_per_server = pool_size_per_server

        # Create pools for each server
        for config in configs:
            self.pools[config.name] = AsyncConnectionPool(config, pool_size=pool_size_per_server)

        with _ACTIVE_POOLS_LOCK:
            _ACTIVE_POOLS.append(self)

    async def invalidate_server(
        self, name: str, new_config: Optional[SMTPServerConfig] = None
    ) -> bool:
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

        # Always capture the pool we're about to displace BEFORE swapping
        # in the replacement, so we can close its sockets cleanly. The
        # previous structure had a branch (same-name replace) that
        # overwrote self.pools[name] without ever closing the displaced
        # pool — orphaning every AsyncSMTPConnection it held.
        old_pool: Optional[AsyncConnectionPool] = self.pools.get(name)

        if new_config is not None:
            self.configs = [(new_config if c.name == name else c) for c in self.configs]
            target_name = new_config.name
            self.pools[target_name] = AsyncConnectionPool(
                new_config,
                pool_size=self._pool_size_per_server,
            )
            # Rename case: drop the old key so the server isn't reachable
            # under its prior name.
            if target_name != name:
                self.pools.pop(name, None)
        # If new_config is None this is a pure force-reset: we still want
        # to close the existing pool so the next acquire opens fresh
        # connections. The pool entry stays in self.pools — close_all()
        # flips _initialized False, so initialize() will rebuild on demand.

        if old_pool is not None:
            try:
                await old_pool.close_all()
            except Exception as e:
                logger.warning(f"close_all error for {name} during invalidate: {e}")

        logger.info(f"Invalidated pool for SMTP server '{name}'")
        return True

    def _candidate_configs(
        self, candidates: Optional[List[SMTPServerConfig]] = None
    ) -> List[SMTPServerConfig]:
        """Snapshot the candidate list. Defaults to self.configs.

        Taking a local snapshot (not a live reference) is important: the
        config list can be mutated by invalidate_server() running on the
        Flask request thread while a campaign-loop task is mid-selection.
        """
        source = candidates if candidates is not None else self.configs
        # list() copies the reference list so a concurrent mutation of
        # self.configs (by invalidate_server) can't shorten the iteration
        # mid-flight. The element objects themselves are still shared.
        return list(source)

    def _select_server_weighted(
        self, candidates: Optional[List[SMTPServerConfig]] = None
    ) -> Optional[SMTPServerConfig]:
        """Select server using weighted random selection."""
        import random

        available = [
            c for c in self._candidate_configs(candidates) if c.can_execute(self.ip_warmup_mode)
        ]

        if not available:
            return None

        total_weight = sum(c.weight for c in available)
        if total_weight <= 0:
            return random.choice(available)

        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for config in available:
            cumulative += config.weight
            if r <= cumulative:
                return config

        return available[-1]

    def _select_server_round_robin(
        self, candidates: Optional[List[SMTPServerConfig]] = None
    ) -> Optional[SMTPServerConfig]:
        """Select server using round-robin."""
        available = [
            c for c in self._candidate_configs(candidates) if c.can_execute(self.ip_warmup_mode)
        ]

        if not available:
            return None

        config = available[self._round_robin_index % len(available)]
        self._round_robin_index += 1
        return config

    def _select_server_priority(
        self, candidates: Optional[List[SMTPServerConfig]] = None
    ) -> Optional[SMTPServerConfig]:
        """Select server by priority."""
        available = [
            c for c in self._candidate_configs(candidates) if c.can_execute(self.ip_warmup_mode)
        ]

        if not available:
            return None

        # Sort by priority (higher is better)
        available.sort(key=lambda c: c.priority, reverse=True)
        return available[0]

    def select_server(
        self, candidates: Optional[List[SMTPServerConfig]] = None
    ) -> Optional[SMTPServerConfig]:
        """Select best available server.

        ``candidates`` lets callers restrict selection to a subset (used by
        ``select_server_for_from`` to rotate only among owners of a given
        From address) without the previous self.configs swap-and-restore
        hack, which was racy under concurrent invalidate_server().
        """
        if self.selection_strategy == "weighted":
            return self._select_server_weighted(candidates)
        elif self.selection_strategy == "round_robin":
            return self._select_server_round_robin(candidates)
        elif self.selection_strategy == "priority":
            return self._select_server_priority(candidates)
        else:
            return self._select_server_weighted(candidates)

    def select_server_for_from(self, from_email: Optional[str]) -> Optional[SMTPServerConfig]:
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
        # Snapshot self.configs once — see _candidate_configs for why the
        # live reference is unsafe under concurrent invalidate_server.
        owners = [
            c
            for c in list(self.configs)
            if c.can_execute(self.ip_warmup_mode) and (c.from_email or "").strip().lower() == target
        ]
        if not owners:
            return None
        if len(owners) == 1:
            return owners[0]
        # Multiple owners — apply normal strategy among them via the
        # candidates parameter instead of swapping self.configs in place.
        return self.select_server(candidates=owners)

    async def acquire(
        self, preferred_server: Optional[str] = None, timeout: float = 10.0, priority: int = 2
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
                raise RuntimeError(f"Preferred SMTP server '{preferred_server}' is not configured")
            config = next((c for c in self.configs if c.name == preferred_server), None)
            if not config:
                raise RuntimeError(f"Preferred SMTP server '{preferred_server}' has no config")
            if not config.can_execute(self.ip_warmup_mode):
                raise RuntimeError(
                    f"Preferred SMTP server '{preferred_server}' is unavailable "
                    f"(rate-limited or circuit open)"
                )
            conn = await self.pools[preferred_server].get_connection(timeout, priority)
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
                    if c.runtime is None:
                        continue
                    cb_stats = c.runtime.circuit_breaker.get_stats()
                    if cb_stats.get("state") == "open":
                        msgs = cb_stats.get("last_error_messages") or []
                        last = msgs[-1] if msgs else "unknown"
                        details.append(f"{c.name}: circuit open — last error: {last}")
                except Exception:
                    pass
            if details:
                raise RuntimeError(
                    "All SMTP servers' circuit breakers are open. " + " | ".join(details)
                )
            raise RuntimeError("No SMTP servers available")

        pool = self.pools[config.name]
        conn = await pool.get_connection(timeout, priority)
        return conn, config

    async def release(self, conn: AsyncSMTPConnection, config: SMTPServerConfig):
        """Release connection back to pool."""
        if config.name in self.pools:
            await self.pools[config.name].release_connection(conn)

    def record_success(self, config: SMTPServerConfig):
        """Record successful send."""
        rt = config.runtime
        assert rt is not None, "SMTPServerRuntime not initialized"
        rt.circuit_breaker.record_success()
        rt.total_sent += 1
        rt.consecutive_failures = 0

    def record_failure(self, config: SMTPServerConfig, error: Exception):
        """Record failed send."""
        rt = config.runtime
        assert rt is not None, "SMTPServerRuntime not initialized"
        rt.circuit_breaker.record_failure(error)
        rt.total_failures += 1
        rt.consecutive_failures += 1

        # Rate-limit detection used to live here as a keyword scan over
        # ``str(error).lower()`` — but by the time record_failure is
        # called, async_sender.categorize_smtp_error has already turned
        # the exception into SMTPRateLimitError when appropriate (using
        # both RFC 5321 status codes and the same keyword fallback). The
        # local scan added nothing except misfires on substrings like
        # "corporate" → matches "rate". Use the typed exception instead.
        if isinstance(error, SMTPRateLimitError):
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
            if rt is None:
                status[c.name] = {"host": c.host, "circuit_state": "unknown", "available": False}
                continue
            stats = rt.circuit_breaker.get_stats()
            status[c.name] = {
                "host": c.host,
                "circuit_state": stats["state"],
                "minute_count": rt.current_minute_count,
                "hour_count": rt.current_hour_count,
                "available": c.can_execute(self.ip_warmup_mode),
                "total_sent": rt.total_sent,
                "consecutive_failures": rt.consecutive_failures,
                "total_failures": rt.total_failures,
                "avg_handshake_latency": rt.avg_handshake_latency
                if hasattr(rt, "avg_handshake_latency")
                else None,
                "avg_send_latency": rt.avg_send_latency
                if hasattr(rt, "avg_send_latency")
                else None,
            }
        return status
