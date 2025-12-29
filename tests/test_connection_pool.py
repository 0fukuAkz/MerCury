"""Tests for SMTP Connection Pooling."""

import pytest
import asyncio
from unittest.mock import patch, Mock, AsyncMock
from unified_sender.engine.connection_pool import (
    SMTPConnectionPool, AsyncConnectionPool, AsyncSMTPConnection,
    SMTPServerConfig, CircuitBreaker
)

@pytest.fixture
def server_config():
    return SMTPServerConfig(
        name="test_server",
        host="smtp.test.com",
        weight=1.0,
        priority=10,
        username="user", # Enable auth
        password="pwd"
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
    with patch('aiosmtplib.SMTP', autospec=True) as MockSMTPClass:
        # Configure the instance returned by the class
        mock_instance = MockSMTPClass.return_value
        
        conn = AsyncSMTPConnection(server_config)
        await conn.connect()
        
        # use_tls is False for STARTTLS (port 587)
        MockSMTPClass.assert_called_with(
            hostname="smtp.test.com", 
            port=587,
            use_tls=False,
            timeout=30
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
    
    with patch('unified_sender.engine.connection_pool.AsyncSMTPConnection') as MockConn:
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

# --- SMTPConnectionPool (Load Balancer) Tests ---

def test_smtp_pool_selection_weighted(server_config, mock_circuit_breaker):
    config1 = server_config
    config1.circuit_breaker = mock_circuit_breaker
    
    config2 = SMTPServerConfig(name="s2", host="h2", weight=2.0)
    config2.circuit_breaker = mock_circuit_breaker
    
    # Fix: use selection_strategy
    pool = SMTPConnectionPool([config1, config2], selection_strategy='weighted')
    
    selected = pool.select_server()
    assert selected in [config1, config2]

def test_smtp_pool_selection_round_robin(server_config, mock_circuit_breaker):
    config1 = server_config
    config1.circuit_breaker = mock_circuit_breaker
    
    config2 = SMTPServerConfig(name="s2", host="h2")
    config2.circuit_breaker = mock_circuit_breaker
    
    pool = SMTPConnectionPool([config1, config2], selection_strategy='round_robin')
    
    s1 = pool.select_server()
    s2 = pool.select_server()
    s3 = pool.select_server()
    
    # Should alternate
    assert s1 != s2
    assert s1 == s3

def test_smtp_pool_selection_priority(server_config, mock_circuit_breaker):
    config1 = server_config # priority 10
    config1.circuit_breaker = mock_circuit_breaker
    
    config2 = SMTPServerConfig(name="s2", host="h2", priority=20)
    config2.circuit_breaker = mock_circuit_breaker
    
    pool = SMTPConnectionPool([config1, config2], selection_strategy='priority')
    
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
        with patch('asyncio.wait_for', side_effect=asyncio.TimeoutError):
             await pool.get_connection(timeout=1.0)

@pytest.mark.asyncio
async def test_pool_release_invalid(server_config):
    pool = AsyncConnectionPool(server_config)
    conn = AsyncMock()
    conn.is_connected = True
    conn.age_seconds = 1000 # Old
    pool.max_connection_age = 100
    
    conn.close = AsyncMock()
    pool.connections.append(conn)
    
    await pool.release_connection(conn)
    
    conn.close.assert_awaited()
    assert conn not in pool.connections
    # Should replenish
    assert pool.available.empty() # because it closed it, didn't return to queue
    # Use internal verify? verify replenish task created?
    # It creates task. Hard to verify without mocking create_task or waiting.


@pytest.mark.asyncio
async def test_smtp_pool_acquire(server_config, mock_circuit_breaker):
    server_config.circuit_breaker = mock_circuit_breaker
    pool = SMTPConnectionPool([server_config])
    
    # Mock the internal AsyncConnectionPool
    mock_async_pool = AsyncMock()
    mock_conn = Mock()
    mock_async_pool.get_connection.return_value = mock_conn
    
    pool.pools = {'test_server': mock_async_pool}
    
    conn, config = await pool.acquire()
    
    assert conn == mock_conn
    assert config == server_config
    mock_async_pool.get_connection.assert_awaited()
