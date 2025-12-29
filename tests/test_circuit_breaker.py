"""Tests for circuit breaker."""

import pytest
import asyncio
from datetime import datetime, UTC, timedelta

from unified_sender.engine.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState
)
from unified_sender.exceptions import SMTPConnectionError, SMTPAuthenticationError


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def test_initial_state_closed(self):
        """Test circuit breaker starts in closed state."""
        cb = CircuitBreaker("test-server")
        
        assert cb.is_available() is True
        assert cb._stats.state == CircuitState.CLOSED
    
    def test_opens_after_threshold_failures(self):
        """Test circuit opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test-server", config)
        
        # Record 3 failures
        for _ in range(3):
            cb.record_failure(SMTPConnectionError("Connection failed"))
        
        # Circuit should be open
        assert cb.is_available() is False
        assert cb._stats.state == CircuitState.OPEN
        assert cb._stats.total_opens == 1
    
    def test_success_resets_failure_count(self):
        """Test success resets failure counter."""
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker("test-server", config)
        
        # Record some failures
        cb.record_failure(Exception("Error 1"))
        cb.record_failure(Exception("Error 2"))
        
        assert cb._stats.failure_count == 2
        
        # Success should reset
        cb.record_success()
        
        assert cb._stats.failure_count == 0
        assert cb._stats.state == CircuitState.CLOSED
    
    def test_half_open_after_timeout(self):
        """Test transition to half-open after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            timeout_seconds=0.1  # Short timeout for testing
        )
        cb = CircuitBreaker("test-server", config)
        
        # Open the circuit
        cb.record_failure(Exception("Error"))
        cb.record_failure(Exception("Error"))
        
        assert cb._stats.state == CircuitState.OPEN
        
        # Wait for timeout
        import time
        time.sleep(0.15)
        
        # Should transition to half-open
        is_available = cb.is_available()
        assert is_available is True  # Half-open allows attempts
    
    def test_half_open_closes_after_successes(self):
        """Test half-open closes after success threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            success_threshold=2,
            timeout_seconds=0
        )
        cb = CircuitBreaker("test-server", config)
        
        # Open circuit
        cb.record_failure(Exception("Error"))
        cb.record_failure(Exception("Error"))
        cb._stats.state = CircuitState.HALF_OPEN  # Force half-open
        
        # Record successes
        cb.record_success()
        cb.record_success()
        
        # Should be closed now
        assert cb._stats.state == CircuitState.CLOSED
    
    def test_half_open_reopens_on_failure(self):
        """Test half-open reopens on any failure."""
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker("test-server", config)
        
        # Open then force half-open
        cb.record_failure(Exception("Error"))
        cb.record_failure(Exception("Error"))
        cb._stats.state = CircuitState.HALF_OPEN
        
        # One failure should reopen
        cb.record_failure(Exception("Error"))
        
        assert cb._stats.state == CircuitState.OPEN
    
    def test_manual_open(self):
        """Test manually opening circuit."""
        cb = CircuitBreaker("test-server")
        
        cb.force_open()
        
        assert cb._stats.state == CircuitState.OPEN
        assert cb.is_available() is False
    
    def test_manual_close(self):
        """Test manually closing circuit."""
        cb = CircuitBreaker("test-server")
        
        # Open circuit
        for _ in range(5):
            cb.record_failure(Exception("Error"))
        
        assert cb._stats.state == CircuitState.OPEN
        
        # Force close
        cb.force_close()
        
        assert cb._stats.state == CircuitState.CLOSED
        assert cb.is_available() is True
    
    def test_rolling_window_failures(self):
        """Test failures outside monitoring window don't count."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            monitor_window_seconds=0.1  # 0.1 second window
        )
        cb = CircuitBreaker("test-server", config)
        
        # Add 2 failures
        cb.record_failure(Exception("Error"))
        cb.record_failure(Exception("Error"))
        
        # Wait for window to expire
        import time
        time.sleep(0.15)
        
        # Add one more - should NOT open (old failures expired)
        cb.record_failure(Exception("Error"))
        
        # Should still be closed
        assert cb._stats.state == CircuitState.CLOSED
    
    def test_get_stats(self):
        """Test statistics reporting."""
        cb = CircuitBreaker("test-server")
        
        cb.record_failure(Exception("Error"))
        cb.record_success()
        
        stats = cb.get_stats()
        
        assert 'state' in stats
        assert 'failure_count' in stats
        assert 'success_count' in stats
        assert 'is_available' in stats
        assert 'total_opens' in stats
    
    def test_reset(self):
        """Test resetting circuit breaker."""
        cb = CircuitBreaker("test-server")
        
        # Record some activity
        cb.record_failure(Exception("Error"))
        cb.record_failure(Exception("Error"))
        
        cb.reset()
        
        assert cb._stats.state == CircuitState.CLOSED
        assert cb._stats.failure_count == 0
        assert len(cb._recent_failures) == 0

