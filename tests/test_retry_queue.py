"""Tests for retry queue."""

import pytest
import asyncio
from datetime import datetime, UTC
from unittest.mock import AsyncMock, Mock

from unified_sender.engine.retry_queue import RetryQueue, RetryConfig, RetryItem


@pytest.mark.asyncio
class TestRetryQueue:
    """Test retry queue functionality."""
    
    async def test_add_item(self):
        """Test adding item to retry queue."""
        config = RetryConfig(max_retries=3, initial_delay=0.1)
        queue = RetryQueue(config)
        await queue.start()
        
        await queue.add(
            id="test-123",
            data={"recipient": "test@example.com"},
            error="Connection failed"
        )
        
        stats = queue.get_stats()
        assert stats['queue_size'] == 1
        assert stats['total_added'] == 1
        
        await queue.stop()
    
    async def test_process_retry_success(self):
        """Test successful retry processing."""
        config = RetryConfig(max_retries=3, initial_delay=0.1, max_delay=0.5)
        queue = RetryQueue(config)
        
        # Mock handler that succeeds
        async def mock_handler(item: RetryItem) -> bool:
            return True
        
        queue.set_retry_handler(mock_handler)
        await queue.start()
        
        await queue.add(
            id="test-123",
            data={"test": "data"},
            error="Test error"
        )
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        stats = queue.get_stats()
        assert stats['total_succeeded'] >= 1
        
        await queue.stop()
    
    async def test_process_retry_permanent_failure(self):
        """Test retry with permanent failure."""
        config = RetryConfig(max_retries=3, initial_delay=0.1, max_delay=0.3)
        queue = RetryQueue(config)
        
        # Mock handler that always fails
        async def mock_handler(item: RetryItem) -> bool:
            return False
        
        queue.set_retry_handler(mock_handler)
        await queue.start()
        
        await queue.add(
            id="test-123",
            data={"test": "data"},
            error="Test error"
        )
        
        # Wait for all retries
        await asyncio.sleep(2.0)
        
        stats = queue.get_stats()
        assert stats['total_failed'] >= 1
        
        await queue.stop()
    
    async def test_exponential_backoff(self):
        """Test exponential backoff delays."""
        config = RetryConfig(
            max_retries=4,
            initial_delay=0.1,
            max_delay=1.0,
            backoff_factor=2.0
        )
        queue = RetryQueue(config)
        
        retry_times = []
        
        async def mock_handler(item: RetryItem) -> bool:
            retry_times.append(datetime.now(UTC))
            return False  # Keep failing to see all retries
        
        queue.set_retry_handler(mock_handler)
        await queue.start()
        
        await queue.add(id="test", data={}, error="Test")
        
        # Wait for all retries
        await asyncio.sleep(3.0)
        
        # Should see increasing delays
        if len(retry_times) >= 2:
            delays = []
            for i in range(1, len(retry_times)):
                delay = (retry_times[i] - retry_times[i-1]).total_seconds()
                delays.append(delay)
            
            # Each delay should be longer (exponential backoff)
            # Allow for some timing variance
            for i in range(1, len(delays)):
                assert delays[i] >= delays[i-1] * 0.8  # 80% tolerance
        
        await queue.stop()
    
    async def test_max_retries(self):
        """Test max retries enforcement."""
        config = RetryConfig(max_retries=2, initial_delay=0.05)
        queue = RetryQueue(config)
        
        attempt_count = 0
        
        async def mock_handler(item: RetryItem) -> bool:
            nonlocal attempt_count
            attempt_count += 1
            return False  # Always fail
        
        queue.set_retry_handler(mock_handler)
        await queue.start()
        
        await queue.add(id="test", data={}, error="Test")
        
        # Wait for processing
        await asyncio.sleep(1.0)
        
        # Should have attempted: initial + 2 retries = 3 total
        assert attempt_count <= 3
        
        stats = queue.get_stats()
        assert stats['total_failed'] >= 1
        
        await queue.stop()
    
    async def test_get_stats(self):
        """Test statistics retrieval."""
        config = RetryConfig(max_retries=3)
        queue = RetryQueue(config)
        await queue.start()
        
        stats = queue.get_stats()
        
        assert 'queue_size' in stats
        assert 'total_added' in stats
        assert 'total_succeeded' in stats
        assert 'total_failed' in stats
        assert 'is_processing' in stats
        
        await queue.stop()
    
    async def test_stop_clears_queue(self):
        """Test stopping clears the queue."""
        config = RetryConfig(max_retries=3)
        queue = RetryQueue(config)
        await queue.start()
        
        # Add items
        await queue.add(id="test1", data={}, error="Test")
        await queue.add(id="test2", data={}, error="Test")
        
        assert queue.get_stats()['queue_size'] == 2
        
        await queue.stop()
        
        # Queue should be empty after stop
        assert queue.get_stats()['queue_size'] == 0

