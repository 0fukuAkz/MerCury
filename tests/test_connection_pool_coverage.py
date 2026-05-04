"""Tests for connection_pool.py coverage."""

import pytest
import asyncio
from unittest.mock import patch
from mercury.engine.connection_pool import (
    SMTPConnectionPool, AsyncConnectionPool, SMTPServerConfig,
    AsyncSMTPConnection
)

@pytest.fixture
def mock_config():
    return SMTPServerConfig(name="Test", host="smtp", weight=0.0)

@pytest.mark.asyncio
async def test_pool_replenish(mock_config):
    pool = AsyncConnectionPool(mock_config, pool_size=2)
    # Mock connect to avoid real network calls
    with patch.object(AsyncSMTPConnection, 'connect', return_value=None):
        await pool._replenish_one()
        assert len(pool.connections) == 1
        
        # Don't exceed pool size
        pool.pool_size = 1
        await pool._replenish_one()
        assert len(pool.connections) == 1

@pytest.mark.asyncio
async def test_pool_get_timeout_replacement(mock_config):
    pool = AsyncConnectionPool(mock_config, pool_size=1)
    
    with patch.object(AsyncSMTPConnection, 'connect', return_value=None):
        await pool.initialize()
        
        # Manually alter the connection to make it stale
        conn = pool.connections[0]
        # Make age huge
        conn.created_at = conn.created_at.replace(year=2000)
        
        # getting connection should see it's stale, close it, and make a new one
        with patch.object(AsyncSMTPConnection, 'close', return_value=None) as mock_close:
            new_conn = await pool.get_connection(timeout=2.0)
            mock_close.assert_called_once()
            assert new_conn != conn

@pytest.mark.asyncio
async def test_pool_release_stale_replenish(mock_config):
    pool = AsyncConnectionPool(mock_config, pool_size=1)
    with patch.object(AsyncSMTPConnection, 'connect', return_value=None):
        conn = await pool.get_connection()
        
        conn.created_at = conn.created_at.replace(year=2000)
        
        with patch.object(AsyncSMTPConnection, 'close', return_value=None):
            await pool.release_connection(conn)
            
            # Replenish should run in background, give it a tick
            await asyncio.sleep(0.01)
            
            assert len(pool.connections) == 1
            assert pool.connections[0] != conn

def test_multi_pool_weighted_zero():
    # Test random choice when weights are 0
    configs = [
        SMTPServerConfig(name="S1", host="smtp", weight=0.0),
        SMTPServerConfig(name="S2", host="smtp", weight=0.0)
    ]
    pool = SMTPConnectionPool(configs, selection_strategy='weighted')
    
    chosen = pool.select_server()
    assert chosen in configs

def test_record_failure_rate_limit(mock_config):
    pool = SMTPConnectionPool([mock_config])
    
    pool.record_failure(mock_config, Exception("rate limit exceeded (421)"))
    
    # Should correctly parse the error string and log it.
    # No direct state assert needed besides checking errors didn't raise
    assert mock_config.total_failures == 1

@pytest.mark.asyncio
async def test_multi_pool_acquire_no_servers():
    configs = [
        SMTPServerConfig(name="S1", host="smtp")
    ]
    pool = SMTPConnectionPool(configs)
    
    # Manually trip breaker
    pool.configs[0].circuit_breaker.record_failure(Exception())
    pool.configs[0].circuit_breaker.record_failure(Exception())
    pool.configs[0].circuit_breaker.record_failure(Exception())
    pool.configs[0].circuit_breaker.record_failure(Exception())
    pool.configs[0].circuit_breaker.record_failure(Exception())
    
    with pytest.raises(RuntimeError, match="No SMTP servers available"):
        await pool.acquire()

def test_status(mock_config):
    pool = SMTPConnectionPool([mock_config])
    status = pool.get_status()
    assert "Test" in status
    assert status['Test']['available'] is True
