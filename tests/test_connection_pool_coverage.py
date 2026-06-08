"""Tests for connection_pool.py coverage."""

import pytest
import asyncio
from unittest.mock import patch
from mercury.engine.connection_pool import (
    SMTPConnectionPool,
    AsyncConnectionPool,
    SMTPServerConfig,
    AsyncSMTPConnection,
)


@pytest.fixture
def mock_config():
    return SMTPServerConfig(name="Test", host="smtp", weight=0.0)


@pytest.mark.asyncio
async def test_pool_replenish(mock_config):
    pool = AsyncConnectionPool(mock_config, pool_size=2)
    # Mock connect to avoid real network calls
    with patch.object(AsyncSMTPConnection, "connect", return_value=None):
        await pool._replenish_one()
        assert len(pool.connections) == 1

        # Don't exceed pool size
        pool.pool_size = 1
        await pool._replenish_one()
        assert len(pool.connections) == 1


@pytest.mark.asyncio
async def test_pool_get_timeout_replacement(mock_config):
    pool = AsyncConnectionPool(mock_config, pool_size=1)

    with patch.object(AsyncSMTPConnection, "connect", return_value=None):
        await pool.initialize()

        # Manually alter the connection to make it stale
        conn = pool.connections[0]
        # Make age huge
        conn.created_at = conn.created_at.replace(year=2000)

        # getting connection should see it's stale, close it, and make a new one
        with patch.object(AsyncSMTPConnection, "close", return_value=None) as mock_close:
            new_conn = await pool.get_connection(timeout=2.0)
            mock_close.assert_called_once()
            assert new_conn != conn


@pytest.mark.asyncio
async def test_pool_release_stale_replenish(mock_config):
    pool = AsyncConnectionPool(mock_config, pool_size=1)
    with patch.object(AsyncSMTPConnection, "connect", return_value=None):
        conn = await pool.get_connection()

        conn.created_at = conn.created_at.replace(year=2000)

        with patch.object(AsyncSMTPConnection, "close", return_value=None):
            await pool.release_connection(conn)

            # Replenish should run in background, give it a tick
            await asyncio.sleep(0.01)

            assert len(pool.connections) == 1
            assert pool.connections[0] != conn


def test_multi_pool_weighted_zero():
    # Test random choice when weights are 0
    configs = [
        SMTPServerConfig(name="S1", host="smtp", weight=0.0),
        SMTPServerConfig(name="S2", host="smtp", weight=0.0),
    ]
    pool = SMTPConnectionPool(configs, selection_strategy="weighted")

    chosen = pool.select_server()
    assert chosen in configs


def test_record_failure_rate_limit(mock_config):
    pool = SMTPConnectionPool([mock_config])

    pool.record_failure(mock_config, Exception("rate limit exceeded (421)"))

    # Should correctly parse the error string and log it.
    # No direct state assert needed besides checking errors didn't raise
    assert mock_config.runtime.total_failures == 1


@pytest.mark.asyncio
async def test_multi_pool_acquire_no_servers():
    configs = [SMTPServerConfig(name="S1", host="smtp")]
    pool = SMTPConnectionPool(configs)

    # Manually trip breaker
    pool.configs[0].runtime.circuit_breaker.record_failure(Exception())
    pool.configs[0].runtime.circuit_breaker.record_failure(Exception())
    pool.configs[0].runtime.circuit_breaker.record_failure(Exception())
    pool.configs[0].runtime.circuit_breaker.record_failure(Exception())
    pool.configs[0].runtime.circuit_breaker.record_failure(Exception())

    # New contract: when all servers' breakers are open, the error
    # includes the root cause (last error from each tripped breaker)
    # so the operator doesn't have to grep failed-emails.txt.
    with pytest.raises(RuntimeError, match=r"circuit breakers are open"):
        await pool.acquire()


def test_status(mock_config):
    pool = SMTPConnectionPool([mock_config])
    status = pool.get_status()
    assert "Test" in status
    assert status["Test"]["available"] is True


def test_latency_tracking(mock_config):
    runtime = mock_config.runtime

    # Initially no latencies
    assert runtime.avg_handshake_latency is None
    assert runtime.avg_send_latency is None

    # Record some handshake latencies
    runtime.record_handshake_latency(1.0)
    runtime.record_handshake_latency(2.0)
    assert runtime.avg_handshake_latency == 1.5
    assert len(runtime.handshake_latencies) == 2

    # Record many handshake latencies to test cap (limit is 50)
    for i in range(100):
        runtime.record_handshake_latency(float(i))
    assert len(runtime.handshake_latencies) == 50
    # Average of last 50: sum(range(50, 100)) / 50 -> 74.5
    assert runtime.avg_handshake_latency == sum(range(50, 100)) / 50.0

    # Record some send latencies
    runtime.record_send_latency(0.1)
    runtime.record_send_latency(0.3)
    assert runtime.avg_send_latency == 0.2
    assert len(runtime.send_latencies) == 2

    # Record many send latencies to test cap (limit is 50)
    for i in range(100):
        runtime.record_send_latency(float(i))
    assert len(runtime.send_latencies) == 50
    assert runtime.avg_send_latency == sum(range(50, 100)) / 50.0


@pytest.mark.asyncio
async def test_async_connection_timing_connect(mock_config):
    # Test that connect and send_message measure timing under the hood
    conn = AsyncSMTPConnection(mock_config)

    # Let's mock aiosmtplib.SMTP.connect, login, and send_message
    with patch("aiosmtplib.SMTP", autospec=True) as MockSMTPClass:
        mock_smtp = MockSMTPClass.return_value

        # Mock connect timing
        # We can implement a tiny sleep inside a custom sleep-inducing coroutine
        async def mock_smtp_connect(*args, **kwargs):
            await asyncio.sleep(0.02)

        async def mock_smtp_login(*args, **kwargs):
            await asyncio.sleep(0.01)

        async def mock_smtp_send_message(*args, **kwargs):
            await asyncio.sleep(0.01)
            return {}, "Sent"

        mock_smtp.connect = mock_smtp_connect
        mock_smtp.login = mock_smtp_login
        mock_smtp.send_message = mock_smtp_send_message
        mock_smtp.is_connected = False

        # First connect
        await conn.connect()

        # Verify latency was logged (it should be > 0.0)
        assert mock_config.runtime.avg_handshake_latency is not None
        assert mock_config.runtime.avg_handshake_latency > 0.0

        # Send message
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = "test@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Hello"
        msg.set_content("World")

        await conn.send_message(msg)

        # Verify send latency was logged too
        assert mock_config.runtime.avg_send_latency is not None
        assert mock_config.runtime.avg_send_latency > 0.0
