"""Tests for SMTP connection pool."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch

from unified_sender.engine.connection_pool import (
    SMTPServerConfig,
    AsyncConnectionPool,
    SMTPConnectionPool,
    ConnectionPoolException
)


@pytest.mark.asyncio
class TestSMTPServerConfig:
    """Test SMTP server configuration."""
    
    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            'name': 'test-smtp',
            'host': 'smtp.example.com',
            'port': 587,
            'username': 'user@example.com',
            'password': 'secretpass',
            'use_tls': True,
            'max_per_minute': 60,
            'max_per_hour': 1000
        }
        
        config = SMTPServerConfig.from_dict(data)
        
        assert config.name == 'test-smtp'
        assert config.host == 'smtp.example.com'
        assert config.port == 587
        assert config.use_tls is True
        assert config.max_per_minute == 60
    
    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = SMTPServerConfig(
            name='test',
            host='smtp.test.com',
            port=465,
            username='test',
            password='pass',
            use_ssl=True
        )
        
        data = config.to_dict()
        
        assert data['name'] == 'test'
        assert data['host'] == 'smtp.test.com'
        assert data['port'] == 465
        assert data['use_ssl'] is True


@pytest.mark.asyncio
class TestAsyncConnectionPool:
    """Test async connection pool."""
    
    async def test_initialize_pool(self):
        """Test connection pool initialization."""
        config = SMTPServerConfig(
            name='test',
            host='smtp.example.com',
            port=587,
            username='test',
            password='pass'
        )
        
        pool = AsyncConnectionPool(config, pool_size=2)
        
        # Mock SMTP connection
        with patch('aiosmtplib.SMTP') as mock_smtp:
            mock_instance = AsyncMock()
            mock_smtp.return_value = mock_instance
            
            await pool.initialize()
            
            assert pool._initialized is True
            assert len(pool._connections) == 2
            
            await pool.close_all()
    
    async def test_get_connection(self):
        """Test getting connection from pool."""
        config = SMTPServerConfig(
            name='test',
            host='smtp.example.com',
            port=587,
            username='test',
            password='pass'
        )
        
        pool = AsyncConnectionPool(config, pool_size=1)
        
        with patch('aiosmtplib.SMTP') as mock_smtp:
            mock_instance = AsyncMock()
            mock_smtp.return_value = mock_instance
            
            await pool.initialize()
            
            # Get connection
            conn = await pool.get_connection(timeout=5.0)
            
            assert conn is not None
            
            # Return connection
            await pool.return_connection(conn)
            
            await pool.close_all()
    
    async def test_connection_timeout(self):
        """Test connection acquisition timeout."""
        config = SMTPServerConfig(
            name='test',
            host='smtp.example.com',
            port=587,
            username='test',
            password='pass'
        )
        
        pool = AsyncConnectionPool(config, pool_size=1)
        
        with patch('aiosmtplib.SMTP') as mock_smtp:
            mock_instance = AsyncMock()
            mock_smtp.return_value = mock_instance
            
            await pool.initialize()
            
            # Get first connection
            conn1 = await pool.get_connection(timeout=1.0)
            
            # Try to get second (should timeout with pool_size=1)
            with pytest.raises(asyncio.TimeoutError):
                await pool.get_connection(timeout=0.1)
            
            # Return first connection
            await pool.return_connection(conn1)
            
            await pool.close_all()


@pytest.mark.asyncio
class TestSMTPConnectionPool:
    """Test multi-server connection pool."""
    
    async def test_multiple_servers(self):
        """Test pool with multiple SMTP servers."""
        configs = [
            SMTPServerConfig(name='smtp1', host='smtp1.com', port=587),
            SMTPServerConfig(name='smtp2', host='smtp2.com', port=587),
        ]
        
        pool = SMTPConnectionPool(configs, pool_size_per_server=2)
        
        assert len(pool._pools) == 2
        assert 'smtp1' in pool._pools
        assert 'smtp2' in pool._pools
    
    async def test_round_robin_selection(self):
        """Test round-robin server selection."""
        configs = [
            SMTPServerConfig(name='smtp1', host='smtp1.com', port=587),
            SMTPServerConfig(name='smtp2', host='smtp2.com', port=587),
        ]
        
        pool = SMTPConnectionPool(configs, pool_size_per_server=1)
        
        with patch('aiosmtplib.SMTP') as mock_smtp:
            mock_instance = AsyncMock()
            mock_smtp.return_value = mock_instance
            
            # Should alternate between servers
            servers_used = []
            for _ in range(4):
                _, config = await pool.acquire(timeout=5.0)
                servers_used.append(config.name)
                # Immediately release to test rotation
                await pool.release(mock_instance, config)
            
            # Should see both servers used
            assert 'smtp1' in servers_used
            assert 'smtp2' in servers_used
            
            await pool.close_all()
    
    async def test_health_tracking(self):
        """Test server health tracking."""
        config = SMTPServerConfig(name='test', host='smtp.test.com', port=587)
        pool = SMTPConnectionPool([config])
        
        # Record failures
        pool.record_failure(config, Exception("Test error"))
        pool.record_failure(config, Exception("Test error 2"))
        
        status = pool.get_status()
        
        assert status['test']['consecutive_failures'] == 2
        assert status['test']['total_failures'] == 2
    
    async def test_get_status(self):
        """Test getting pool status."""
        configs = [
            SMTPServerConfig(name='smtp1', host='smtp1.com', port=587),
            SMTPServerConfig(name='smtp2', host='smtp2.com', port=587),
        ]
        
        pool = SMTPConnectionPool(configs, pool_size_per_server=2)
        
        status = pool.get_status()
        
        assert 'smtp1' in status
        assert 'smtp2' in status
        assert status['smtp1']['total_sent'] == 0
        assert status['smtp1']['consecutive_failures'] == 0

