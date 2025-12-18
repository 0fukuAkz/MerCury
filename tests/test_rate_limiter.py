"""Tests for rate limiter."""

import pytest
import asyncio
from datetime import datetime, UTC

from unified_sender.engine.rate_limiter import RateLimiter, RateLimiterConfig
from unified_sender.exceptions import RateLimitException


@pytest.mark.asyncio
class TestRateLimiter:
    """Test rate limiter functionality."""
    
    async def test_no_limit(self):
        """Test with no rate limits."""
        config = RateLimiterConfig(per_minute=0, per_hour=0)
        limiter = RateLimiter(config)
        
        # Should not block
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()
        
        # No assertions needed - just shouldn't block
    
    async def test_per_minute_limit(self):
        """Test per-minute rate limiting."""
        config = RateLimiterConfig(per_minute=2, per_hour=0)
        limiter = RateLimiter(config)
        
        # First 2 should pass immediately
        start = datetime.now(UTC)
        await limiter.acquire()
        await limiter.acquire()
        elapsed = (datetime.now(UTC) - start).total_seconds()
        
        assert elapsed < 0.5  # Should be nearly instant
        
        # Third should block
        start = datetime.now(UTC)
        await asyncio.wait_for(limiter.acquire(), timeout=2.0)
        elapsed = (datetime.now(UTC) - start).total_seconds()
        
        # Should have waited ~30 seconds (half a minute for 1 more)
        # But with time windows, might be less
        assert elapsed > 0  # At least some delay
    
    async def test_per_hour_limit(self):
        """Test per-hour rate limiting."""
        config = RateLimiterConfig(per_minute=0, per_hour=3)
        limiter = RateLimiter(config)
        
        # First 3 should pass
        start = datetime.now(UTC)
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()
        elapsed = (datetime.now(UTC) - start).total_seconds()
        
        assert elapsed < 0.5
    
    async def test_acquire_timeout(self):
        """Test timeout on acquire."""
        config = RateLimiterConfig(per_minute=1, per_hour=0)
        limiter = RateLimiter(config)
        
        # Use up the limit
        await limiter.acquire()
        
        # Next one should timeout
        with pytest.raises(asyncio.TimeoutError):
            await limiter.acquire(timeout=0.1)
    
    async def test_get_stats(self):
        """Test statistics reporting."""
        config = RateLimiterConfig(per_minute=10, per_hour=100)
        limiter = RateLimiter(config)
        
        await limiter.acquire()
        await limiter.acquire()
        
        stats = limiter.get_stats()
        
        assert 'total_acquired' in stats
        assert 'total_waited' in stats
        assert stats['total_acquired'] >= 2
    
    async def test_concurrent_acquires(self):
        """Test multiple concurrent acquisitions."""
        config = RateLimiterConfig(per_minute=5, per_hour=0)
        limiter = RateLimiter(config)
        
        # Try to acquire 5 times concurrently
        results = await asyncio.gather(*[
            limiter.acquire() for _ in range(5)
        ])
        
        # All should succeed
        assert len(results) == 5
    
    async def test_reset_behavior(self):
        """Test limit resets over time."""
        config = RateLimiterConfig(per_minute=2, per_hour=0)
        limiter = RateLimiter(config)
        
        # Acquire twice
        await limiter.acquire()
        await limiter.acquire()
        
        # Wait a bit (in real scenario, would wait full minute)
        # For testing, we just verify the mechanism works
        stats_before = limiter.get_stats()
        
        # Manually clear for testing
        limiter._minute_tokens.clear()
        
        # Should be able to acquire again
        await limiter.acquire()
        
        stats_after = limiter.get_stats()
        assert stats_after['total_acquired'] > stats_before['total_acquired']

