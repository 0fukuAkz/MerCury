"""Tests targeting full coverage of SMTPConnectionPool and AsyncConnectionPool."""

import asyncio
import time
from datetime import datetime, timedelta, UTC
from unittest.mock import patch
import pytest
from mercury.engine.connection_pool import (
    SMTPConnectionPool,
    AsyncConnectionPool,
    SMTPServerConfig,
    AsyncSMTPConnection,
)

@pytest.fixture
def base_config():
    return SMTPServerConfig(
        name="primary",
        host="smtp.gmail.com",
        port=587,
        username="user",
        password="pwd",
        tls_mode="starttls",
        use_auth=True,
        max_per_minute=5,
        max_per_hour=10,
    )

@pytest.mark.asyncio
async def test_warmup_mode_rate_limits(base_config):
    # Set max per minute to 20 so we can test warmup limits capped at 10
    base_config.max_per_minute = 20
    # Set created_at to 12 hours ago (age <= 1 day)
    base_config.created_at_timestamp = time.time() - 43200
    base_config.total_sent_historical = 10
    
    # Under warmup mode, max per minute should be capped at 2 (instead of 20)
    # and max per hour capped at 10.
    assert base_config.check_rate_limits(ip_warmup_mode=True) is True
    
    # Increment twice
    base_config.increment_counters()
    base_config.increment_counters()
    
    # The 3rd should exceed minute limit (cap of 2)
    assert base_config.check_rate_limits(ip_warmup_mode=True) is False
    
    # Test age <= 3 days limit (cap is 5)
    base_config.created_at_timestamp = time.time() - 2 * 86400
    base_config.total_sent_historical = 100  # make sure it is > 50 so we don't fall into the <= 50 branch
    base_config.runtime.current_minute_count = 4
    assert base_config.check_rate_limits(ip_warmup_mode=True) is True
    base_config.increment_counters()
    assert base_config.check_rate_limits(ip_warmup_mode=True) is False
    
    # Test age <= 7 days limit (cap is 10)
    base_config.created_at_timestamp = time.time() - 5 * 86400
    base_config.total_sent_historical = 300  # make sure it is > 200 so we don't fall into the <= 200 branch
    base_config.runtime.current_minute_count = 9
    assert base_config.check_rate_limits(ip_warmup_mode=True) is True
    base_config.increment_counters()
    assert base_config.check_rate_limits(ip_warmup_mode=True) is False

def test_rate_limits_counter_reset(base_config):
    rt = base_config.runtime
    rt.current_minute_count = 10
    rt.current_hour_count = 100
    
    # Set resets to past
    rt.last_minute_reset = datetime.now(UTC) - timedelta(seconds=61)
    rt.last_hour_reset = datetime.now(UTC) - timedelta(seconds=3601)
    
    # Check rate limit should reset counters
    assert base_config.check_rate_limits() is True
    assert rt.current_minute_count == 0
    assert rt.current_hour_count == 0

@pytest.mark.asyncio
async def test_tls_mode_none_warning(base_config):
    # Port 587 with tls_mode='none' should trigger warning log
    base_config.tls_mode = "none"
    conn = AsyncSMTPConnection(base_config)
    
    from unittest.mock import AsyncMock
    with patch("aiosmtplib.SMTP") as MockSMTP, \
         patch("mercury.engine.connection_pool.logger") as mock_logger:
        mock_smtp = MockSMTP.return_value
        mock_smtp.connect = AsyncMock()
        mock_smtp.starttls = AsyncMock()
        mock_smtp.login = AsyncMock()
        await conn.connect()
        mock_logger.warning.assert_called_once()
        assert "configured with tls_mode='none' on port %d" in mock_logger.warning.call_args[0][0]

@pytest.mark.asyncio
async def test_initialize_pool_all_fail(base_config):
    pool = AsyncConnectionPool(base_config, pool_size=3)
    # Mock connect to always fail
    with patch.object(AsyncSMTPConnection, "connect", side_effect=Exception("SMTP Down")):
        with pytest.raises(Exception, match="SMTP Down"):
            await pool.initialize()
            
    assert pool._initialized is False

@pytest.mark.asyncio
async def test_priority_queueing_waiters(base_config):
    pool = AsyncConnectionPool(base_config, pool_size=1)
    
    async def mock_connect(self):
        self.is_connected = True
        
    with patch.object(AsyncSMTPConnection, "connect", mock_connect):
        # Initialize pool
        await pool.initialize()
        
        # Acquire the only connection
        conn1 = await pool.get_connection()
        
        # Start two concurrent waiters with different priorities
        # Future 1: low priority (3)
        # Future 2: high priority (1)
        waiter1_task = asyncio.create_task(pool.get_connection(priority=3))
        waiter2_task = asyncio.create_task(pool.get_connection(priority=1))
        
        # yield control so they enter queue
        await asyncio.sleep(0.01)
        
        # Release connection 1. Waiter 2 (high priority 1) must be resolved first.
        await pool.release_connection(conn1)
        
        res_conn = await waiter2_task
        assert res_conn == conn1
        
        # waiter 1 task is still pending because connection is held by waiter 2 now
        assert not waiter1_task.done()
        
        # Release again to resolve waiter 1
        await pool.release_connection(res_conn)
        res_conn2 = await waiter1_task
        assert res_conn2 == conn1

@pytest.mark.asyncio
async def test_connection_connect_failures_get_connection(base_config):
    pool = AsyncConnectionPool(base_config, pool_size=1)
    call_count = 0
    
    async def mock_connect(self):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            self.is_connected = True
        else:
            raise Exception("Connect Fail")
            
    with patch.object(AsyncSMTPConnection, "connect", mock_connect):
        # First acquire opens slot 1 and succeeds
        conn = await pool.get_connection()
        
        # Make it stale
        conn.is_connected = False
        await pool.available.put(conn)
        
        # Next get_connection discards slot 1 and tries to reopen, raising connect exception
        with pytest.raises(Exception, match="Connect Fail"):
            await pool.get_connection()

@pytest.mark.asyncio
async def test_invalidate_server_rename_and_exception(base_config):
    pool = SMTPConnectionPool([base_config])
    
    # Rename server from primary -> backup
    new_config = SMTPServerConfig(
        name="backup",
        host="smtp.backup.com",
    )
    
    # Invalidate server
    assert await pool.invalidate_server("primary", new_config) is True
    assert "backup" in pool.pools
    assert "primary" not in pool.pools
    
    # Test closing pool raises exception inside invalidate
    old_pool = pool.pools["backup"]
    with patch.object(old_pool, "close_all", side_effect=Exception("Close Error")):
        # Invalidate again, should log warning but not raise
        assert await pool.invalidate_server("backup") is True

def test_select_server_priority(base_config):
    config_low = SMTPServerConfig(name="low", host="smtp", priority=1)
    config_high = SMTPServerConfig(name="high", host="smtp", priority=5)
    
    pool = SMTPConnectionPool([config_low, config_high], selection_strategy="priority")
    assert pool.select_server() == config_high

def test_select_server_for_from(base_config):
    config_a = SMTPServerConfig(name="S1", host="smtp", from_email="alice@example.com")
    config_b = SMTPServerConfig(name="S2", host="smtp", from_email="bob@example.com")
    
    pool = SMTPConnectionPool([config_a, config_b])
    
    # Test empty email
    assert pool.select_server_for_from("") is None
    assert pool.select_server_for_from(None) is None
    
    # Test match
    assert pool.select_server_for_from("alice@example.com") == config_a
    assert pool.select_server_for_from("bob@example.com") == config_b
    assert pool.select_server_for_from("charlie@example.com") is None

@pytest.mark.asyncio
async def test_acquire_preferred_server_edge_cases(base_config):
    pool = SMTPConnectionPool([base_config])
    
    # 1. Preferred server not in pool
    with pytest.raises(RuntimeError, match="Preferred SMTP server 'nope' is not configured"):
        await pool.acquire(preferred_server="nope")
        
    # 2. Preferred server is unavailable (rate-limited)
    base_config.runtime.circuit_breaker.record_failure(Exception())
    base_config.runtime.circuit_breaker.record_failure(Exception())
    base_config.runtime.circuit_breaker.record_failure(Exception())
    base_config.runtime.circuit_breaker.record_failure(Exception())
    base_config.runtime.circuit_breaker.record_failure(Exception()) # trip breaker
    
    with pytest.raises(RuntimeError, match="Preferred SMTP server 'primary' is unavailable"):
        await pool.acquire(preferred_server="primary")

def test_remove_pool_active_pools_value_error(base_config):
    pool = SMTPConnectionPool([base_config])
    # manually clear registry to cause ValueError on close_all remove
    with patch("mercury.engine.connection_pool._ACTIVE_POOLS", []):
        # Should not raise exception
        asyncio.run(pool.close_all())
