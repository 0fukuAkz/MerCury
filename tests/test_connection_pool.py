"""Tests for SMTP Connection Pooling."""

import pytest
import asyncio
from unittest.mock import patch, Mock, AsyncMock
from mercury.engine.connection_pool import (
    SMTPConnectionPool,
    AsyncConnectionPool,
    AsyncSMTPConnection,
    SMTPServerConfig,
    CircuitBreaker,
)


@pytest.fixture
def server_config():
    return SMTPServerConfig(
        name="test_server",
        host="smtp.test.com",
        weight=1.0,
        priority=10,
        username="user",  # Enable auth
        password="pwd",
    )


@pytest.fixture
def mock_circuit_breaker():
    cb = Mock(spec=CircuitBreaker)
    cb.is_available.return_value = True
    return cb


# --- AsyncSMTPConnection Tests ---


@pytest.mark.asyncio
async def test_async_connection_connect(server_config):
    # Patch the class aiosmtplib.SMTP
    with patch("aiosmtplib.SMTP", autospec=True) as MockSMTPClass:
        # Configure the instance returned by the class
        mock_instance = MockSMTPClass.return_value

        conn = AsyncSMTPConnection(server_config)
        await conn.connect()

        # use_tls is False for STARTTLS (port 587)
        MockSMTPClass.assert_called_with(
            hostname="smtp.test.com", port=587, use_tls=False, timeout=30
        )
        # Verify login called on the instance
        mock_instance.login.assert_called_with("user", "pwd")


@pytest.mark.asyncio
async def test_async_connection_send(server_config):
    conn = AsyncSMTPConnection(server_config)

    # Just set is_connected directly since it's an instance attribute
    conn.is_connected = True
    conn.client = AsyncMock()

    await conn.send_message("msg")
    conn.client.send_message.assert_awaited_with("msg")


# --- AsyncConnectionPool Tests ---


@pytest.mark.asyncio
async def test_async_pool_initialization(server_config):
    pool = AsyncConnectionPool(server_config, pool_size=2)

    with patch("mercury.engine.connection_pool.AsyncSMTPConnection") as MockConn:
        mock_instance = AsyncMock()
        MockConn.return_value = mock_instance

        await pool.initialize()

        assert len(pool.connections) == 2

        # Check queue size - available queue stores connections
        assert pool.available.qsize() == 2


@pytest.mark.asyncio
async def test_async_pool_get_release(server_config):
    pool = AsyncConnectionPool(server_config, pool_size=1)

    # Manually populate
    mock_conn = AsyncMock()
    # Fix: Set attributes directly for property access compatibility
    mock_conn.is_connected = True
    mock_conn.idle_seconds = 0.0
    mock_conn.age_seconds = 0.0

    pool.connections.append(mock_conn)
    await pool.available.put(mock_conn)
    pool._initialized = True

    # Get
    conn = await pool.get_connection()
    assert conn == mock_conn
    assert pool.available.empty()

    # Release
    await pool.release_connection(conn)
    assert pool.available.qsize() == 1


# --- Liveness probe (is_alive) + checkout pre-ping ---
#
# Regression coverage for "SMTP server not responding to commands": a pooled
# connection that an idle server / NAT / firewall closed server-side keeps
# is_connected=True locally, so the old heuristics happily reused it and the
# next MAIL FROM hit a half-open socket. The pre-ping NOOPs the server before
# committing a real message.


@pytest.mark.asyncio
async def test_is_alive_true_when_noop_succeeds(server_config):
    conn = AsyncSMTPConnection(server_config)
    conn.is_connected = True
    conn.client = AsyncMock()
    conn.client.noop = AsyncMock(return_value=(250, b"OK"))

    assert await conn.is_alive() is True
    conn.client.noop.assert_awaited_once()


@pytest.mark.asyncio
async def test_is_alive_false_and_marks_dead_when_noop_fails(server_config):
    conn = AsyncSMTPConnection(server_config)
    conn.is_connected = True
    conn.client = AsyncMock()
    conn.client.noop = AsyncMock(side_effect=ConnectionResetError("peer closed"))

    assert await conn.is_alive() is False
    # Marked dead so the pool's reuse check discards it.
    assert conn.is_connected is False


@pytest.mark.asyncio
async def test_is_alive_false_without_probing_when_not_connected(server_config):
    conn = AsyncSMTPConnection(server_config)
    conn.is_connected = False
    conn.client = AsyncMock()

    assert await conn.is_alive() is False
    conn.client.noop.assert_not_awaited()


@pytest.mark.asyncio
async def test_is_alive_times_out_on_half_open_socket(server_config):
    """A NOOP that hangs (lost FIN, read blocks) must not hang the pool."""
    conn = AsyncSMTPConnection(server_config)
    conn.is_connected = True
    conn.client = AsyncMock()

    async def _never_returns():
        await asyncio.sleep(10)

    conn.client.noop = AsyncMock(side_effect=_never_returns)

    assert await conn.is_alive(timeout=0.05) is False
    assert conn.is_connected is False


def _pooled_conn(*, idle: float, alive: bool) -> AsyncMock:
    conn = AsyncMock(spec=AsyncSMTPConnection)
    conn.is_connected = True
    conn.age_seconds = idle
    conn.idle_seconds = idle
    conn.is_alive = AsyncMock(return_value=alive)
    conn.close = AsyncMock()
    return conn


@pytest.mark.asyncio
async def test_get_connection_discards_dead_idle_connection(server_config):
    """Stale conn (idle past threshold, NOOP fails) is discarded, not handed out.

    This is the bug: idle_seconds=30 is *under* max_idle_time (60), so the old
    code reused it. The pre-ping now catches it and the pool opens a fresh one.
    """
    pool = AsyncConnectionPool(server_config, pool_size=1, pre_ping_idle_threshold=5.0)
    pool._initialized = True

    stale = _pooled_conn(idle=30.0, alive=False)
    pool.connections.append(stale)
    await pool.available.put(stale)

    fresh = _pooled_conn(idle=0.0, alive=True)
    fresh.connect = AsyncMock()

    with patch("mercury.engine.connection_pool.AsyncSMTPConnection", return_value=fresh):
        conn = await pool.get_connection(timeout=5.0)

    assert conn is fresh  # got the healthy replacement
    stale.is_alive.assert_awaited_once()  # we DID pre-ping the idle conn
    stale.close.assert_awaited_once()  # ...and discarded the dead one
    assert stale not in pool.connections


@pytest.mark.asyncio
async def test_get_connection_skips_preping_for_hot_connection(server_config):
    """A connection idle within the trust window is reused with no NOOP."""
    pool = AsyncConnectionPool(server_config, pool_size=1, pre_ping_idle_threshold=5.0)
    pool._initialized = True

    hot = _pooled_conn(idle=0.5, alive=True)
    pool.connections.append(hot)
    await pool.available.put(hot)

    conn = await pool.get_connection()

    assert conn is hot
    hot.is_alive.assert_not_awaited()  # fast path: no round-trip


@pytest.mark.asyncio
async def test_get_connection_reuses_idle_connection_that_passes_preping(server_config):
    """Idle past the window but still alive → pinged once, then reused."""
    pool = AsyncConnectionPool(server_config, pool_size=1, pre_ping_idle_threshold=5.0)
    pool._initialized = True

    warm = _pooled_conn(idle=20.0, alive=True)
    pool.connections.append(warm)
    await pool.available.put(warm)

    conn = await pool.get_connection()

    assert conn is warm
    warm.is_alive.assert_awaited_once()


# --- SMTPConnectionPool (Load Balancer) Tests ---


def test_smtp_pool_selection_weighted(server_config, mock_circuit_breaker):
    config1 = server_config
    config1.runtime.circuit_breaker = mock_circuit_breaker

    config2 = SMTPServerConfig(name="s2", host="h2", weight=2.0)
    config2.runtime.circuit_breaker = mock_circuit_breaker

    # Fix: use selection_strategy
    pool = SMTPConnectionPool([config1, config2], selection_strategy="weighted")

    selected = pool.select_server()
    assert selected in [config1, config2]


def test_smtp_pool_selection_round_robin(server_config, mock_circuit_breaker):
    config1 = server_config
    config1.runtime.circuit_breaker = mock_circuit_breaker

    config2 = SMTPServerConfig(name="s2", host="h2")
    config2.runtime.circuit_breaker = mock_circuit_breaker

    pool = SMTPConnectionPool([config1, config2], selection_strategy="round_robin")

    s1 = pool.select_server()
    s2 = pool.select_server()
    s3 = pool.select_server()

    # Should alternate
    assert s1 != s2
    assert s1 == s3


def test_smtp_pool_selection_priority(server_config, mock_circuit_breaker):
    config1 = server_config  # priority 10
    config1.runtime.circuit_breaker = mock_circuit_breaker

    config2 = SMTPServerConfig(name="s2", host="h2", priority=20)
    config2.runtime.circuit_breaker = mock_circuit_breaker

    pool = SMTPConnectionPool([config1, config2], selection_strategy="priority")

    selected = pool.select_server()
    assert selected == config2


# --- Edge Cases ---


@pytest.mark.asyncio
async def test_async_connection_send_failure(server_config):
    conn = AsyncSMTPConnection(server_config)
    conn.is_connected = True
    conn.client = AsyncMock()
    conn.client.send_message.side_effect = Exception("Send failed")

    with pytest.raises(Exception, match="Send failed"):
        await conn.send_message("msg")

    assert conn.is_connected is False


@pytest.mark.asyncio
async def test_pool_get_timeout(server_config):
    # Set small timeout
    config = server_config
    pool = AsyncConnectionPool(config, pool_size=1)
    # Fill pool
    conn = AsyncMock()
    pool.connections.append(conn)
    # Don't put in available queue -> it's busy

    # get_connection with timeout
    with pytest.raises(asyncio.TimeoutError):
        # We need to mock asyncio.wait_for logic or relying on real behavior?
        # Real behavior needs time. We can mock asyncio.wait_for
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await pool.get_connection(timeout=1.0)


@pytest.mark.asyncio
async def test_pool_release_invalid(server_config):
    pool = AsyncConnectionPool(server_config)
    conn = AsyncMock()
    conn.is_connected = True
    conn.age_seconds = 1000  # Old
    pool.max_connection_age = 100

    conn.close = AsyncMock()
    pool.connections.append(conn)

    await pool.release_connection(conn)

    conn.close.assert_awaited()
    assert conn not in pool.connections
    # Should replenish
    assert pool.available.empty()  # because it closed it, didn't return to queue
    # Use internal verify? verify replenish task created?
    # It creates task. Hard to verify without mocking create_task or waiting.


@pytest.mark.asyncio
async def test_smtp_pool_acquire(server_config, mock_circuit_breaker):
    server_config.runtime.circuit_breaker = mock_circuit_breaker
    pool = SMTPConnectionPool([server_config])

    # Mock the internal AsyncConnectionPool
    mock_async_pool = AsyncMock()
    mock_conn = Mock()
    mock_async_pool.get_connection.return_value = mock_conn

    pool.pools = {"test_server": mock_async_pool}

    conn, config = await pool.acquire()

    assert conn == mock_conn
    assert config == server_config
    mock_async_pool.get_connection.assert_awaited()
