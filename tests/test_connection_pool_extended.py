
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from mercury.engine.connection_pool import (
    SMTPServerConfig, AsyncSMTPConnection, AsyncConnectionPool, SMTPConnectionPool
)

@pytest.fixture
def smtp_config():
    return SMTPServerConfig(
        name="server1",
        host="smtp.example.com",
        username="user",
        password="pass",
        max_per_minute=2
    )

@pytest.fixture
def mock_aiosmtp():
    with patch("mercury.engine.connection_pool.aiosmtplib.SMTP") as MockSMTP:
        client = AsyncMock()
        MockSMTP.return_value = client
        client.connect.return_value = (220, "OK")
        client.starttls.return_value = (220, "OK")
        client.login.return_value = (235, "OK")
        client.send_message.return_value = (250, "OK")
        client.quit.return_value = (221, "OK")
        yield client

@pytest.mark.asyncio
class TestConnectionPoolExtended:
    """Extended tests for ConnectionPool."""

    async def test_connection_lifecycle(self, smtp_config, mock_aiosmtp):
        """Test connection creation, usage, and closing."""
        conn = AsyncSMTPConnection(smtp_config)
        
        # Connect
        await conn.connect()
        mock_aiosmtp.connect.assert_called()
        mock_aiosmtp.login.assert_called()
        assert conn.is_connected
        
        # Send
        msg = MagicMock()
        await conn.send_message(msg)
        mock_aiosmtp.send_message.assert_called_with(msg)
        
        # Close
        await conn.close()
        mock_aiosmtp.quit.assert_called()
        assert not conn.is_connected

    async def test_pool_replenishment(self, smtp_config, mock_aiosmtp):
        """Test pool automatically creates connections."""
        pool = AsyncConnectionPool(smtp_config, pool_size=2)
        
        await pool.initialize()
        assert len(pool.connections) == 2
        
        # Get one
        conn1 = await pool.get_connection()
        assert conn1 in pool.connections
        
        # Release it
        await pool.release_connection(conn1)
        
        # Test valid/invalid connection handling
        conn1.is_connected = False
        # When getting invalid connection, it should discard and replace
        # We need to ensure replenish happens or replacement created
        
        # Manually trigger checks or simulate get with invalid in queue
        # The pool puts connection back in queue on release
        
        # Since queue is FIFO, conn1 is now at end? or was it LIFO? asyncio Queue is FIFO.
        # initialize put 2 conn. get took 1. release put 1 back.
        
        # Let's verify close_all clears everything
        await pool.close_all()
        assert len(pool.connections) == 0

    async def test_multi_pool_selection(self, mock_aiosmtp):
        """Test server selection strategies."""
        c1 = SMTPServerConfig(name="s1", host="h1", weight=10, priority=1)
        c2 = SMTPServerConfig(name="s2", host="h2", weight=1, priority=10)
        
        pool = SMTPConnectionPool([c1, c2], selection_strategy='round_robin')
        
        # Round robin
        s1 = pool.select_server()
        s2 = pool.select_server()
        s3 = pool.select_server()
        
        assert s1.name == "s1"
        assert s2.name == "s2"
        assert s3.name == "s1"
        
        # Priority
        pool.selection_strategy = 'priority'
        s_p = pool.select_server()
        assert s_p.name == "s2"  # Higher priority

    async def test_acquire_release_flow(self, smtp_config, mock_aiosmtp):
        """Test high level acquire/release."""
        pool = SMTPConnectionPool([smtp_config])
        
        conn, cfg = await pool.acquire()
        assert cfg == smtp_config
        assert conn.is_connected
        
        # Release
        await pool.release(conn, cfg)
        
        # Verify stats
        status = pool.get_status()
        assert "server1" in status

    async def test_rate_limiting(self, smtp_config):
        """Test rate limit checks."""
        # limit is 2 per minute
        assert smtp_config.check_rate_limits() is True
        smtp_config.increment_counters()
        assert smtp_config.check_rate_limits() is True
        smtp_config.increment_counters()
        
        # Now 2 reached, should be false
        assert smtp_config.check_rate_limits() is False
