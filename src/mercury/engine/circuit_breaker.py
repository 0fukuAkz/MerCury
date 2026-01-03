"""Circuit breaker pattern for SMTP servers."""

import logging
from datetime import datetime, timedelta, UTC
from typing import Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, field

from ..exceptions import SMTPException, SMTPConnectionError

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Too many failures, stop trying
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5  # Open circuit after N failures
    success_threshold: int = 2  # Close circuit after N successes in half-open
    timeout_seconds: int = 60   # Time to wait before trying half-open
    monitor_window_seconds: int = 300  # Rolling window for failure counting


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker."""
    state: CircuitState
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    total_opens: int = 0
    total_trips: int = 0  # Total state changes
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'state': self.state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'last_success_time': self.last_success_time.isoformat() if self.last_success_time else None,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None,
            'total_opens': self.total_opens,
            'total_trips': self.total_trips
        }


class CircuitBreaker:
    """
    Circuit breaker for SMTP servers.
    
    Prevents repeated attempts to failing servers by temporarily
    disabling them after consecutive failures.
    """
    
    def __init__(self, server_name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker.
        
        Args:
            server_name: Name of SMTP server being protected
            config: Circuit breaker configuration
        """
        self.server_name = server_name
        self.config = config or CircuitBreakerConfig()
        self._stats = CircuitBreakerStats(state=CircuitState.CLOSED)
        
        # Rolling window for failure tracking
        self._recent_failures: list[datetime] = []
    
    def is_available(self) -> bool:
        """
        Check if circuit allows operations.
        
        Returns:
            True if circuit is closed or half-open
        """
        current_state = self._get_current_state()
        
        if current_state == CircuitState.OPEN:
            logger.warning(
                f"🚫 Circuit breaker OPEN for {self.server_name} "
                f"(failures: {self._stats.failure_count})"
            )
            return False
        
        return True
    
    def _get_current_state(self) -> CircuitState:
        """
        Get current circuit state, handling automatic transitions.
        
        Returns:
            Current circuit state
        """
        # If closed, stay closed
        if self._stats.state == CircuitState.CLOSED:
            return CircuitState.CLOSED
        
        # If open, check if timeout elapsed
        if self._stats.state == CircuitState.OPEN:
            if self._stats.opened_at:
                elapsed = (datetime.now(UTC) - self._stats.opened_at).total_seconds()
                if elapsed >= self.config.timeout_seconds:
                    # Transition to half-open
                    logger.info(
                        f"🔄 Circuit breaker transitioning to HALF-OPEN for {self.server_name} "
                        f"(timeout elapsed: {elapsed:.1f}s)"
                    )
                    self._stats.state = CircuitState.HALF_OPEN
                    self._stats.success_count = 0
                    self._stats.total_trips += 1
                    return CircuitState.HALF_OPEN
            return CircuitState.OPEN
        
        # If half-open, stay half-open
        return CircuitState.HALF_OPEN
    
    def record_success(self):
        """Record successful operation."""
        current_state = self._get_current_state()
        now = datetime.now(UTC)
        
        self._stats.last_success_time = now
        
        if current_state == CircuitState.HALF_OPEN:
            self._stats.success_count += 1
            
            # Close circuit if enough successes
            if self._stats.success_count >= self.config.success_threshold:
                logger.info(
                    f"✅ Circuit breaker CLOSED for {self.server_name} "
                    f"(successes: {self._stats.success_count})"
                )
                self._stats.state = CircuitState.CLOSED
                self._stats.failure_count = 0
                self._stats.success_count = 0
                self._recent_failures.clear()
                self._stats.total_trips += 1
        
        elif current_state == CircuitState.CLOSED:
            # Reset failure counter on success
            if self._stats.failure_count > 0:
                self._stats.failure_count = 0
                self._recent_failures.clear()
    
    def record_failure(self, error: Exception):
        """
        Record failed operation.
        
        Args:
            error: Exception that occurred
        """
        current_state = self._get_current_state()
        now = datetime.now(UTC)
        
        self._stats.last_failure_time = now
        self._stats.failure_count += 1
        self._recent_failures.append(now)
        
        # Clean old failures outside monitoring window
        cutoff = now - timedelta(seconds=self.config.monitor_window_seconds)
        self._recent_failures = [
            f for f in self._recent_failures if f > cutoff
        ]
        
        # Check if we should open the circuit
        if current_state == CircuitState.CLOSED:
            if len(self._recent_failures) >= self.config.failure_threshold:
                logger.error(
                    f"⚠️  Circuit breaker OPENING for {self.server_name} "
                    f"({len(self._recent_failures)} failures in {self.config.monitor_window_seconds}s)"
                )
                self._stats.state = CircuitState.OPEN
                self._stats.opened_at = now
                self._stats.total_opens += 1
                self._stats.total_trips += 1
        
        elif current_state == CircuitState.HALF_OPEN:
            # Any failure in half-open immediately opens circuit
            logger.warning(
                f"⚠️  Circuit breaker RE-OPENING for {self.server_name} "
                f"(failure during half-open state)"
            )
            self._stats.state = CircuitState.OPEN
            self._stats.opened_at = now
            self._stats.success_count = 0
            self._stats.total_opens += 1
            self._stats.total_trips += 1
    
    def force_open(self):
        """Manually open circuit (for maintenance, etc.)."""
        logger.warning(f"🔒 Manually opening circuit for {self.server_name}")
        self._stats.state = CircuitState.OPEN
        self._stats.opened_at = datetime.now(UTC)
        self._stats.total_opens += 1
    
    def force_close(self):
        """Manually close circuit (override)."""
        logger.info(f"🔓 Manually closing circuit for {self.server_name}")
        self._stats.state = CircuitState.CLOSED
        self._stats.failure_count = 0
        self._stats.success_count = 0
        self._recent_failures.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        current_state = self._get_current_state()
        
        stats = self._stats.to_dict()
        stats['state'] = current_state.value  # Get current state
        stats['recent_failures'] = len(self._recent_failures)
        stats['is_available'] = current_state != CircuitState.OPEN
        
        if self._stats.opened_at and current_state == CircuitState.OPEN:
            elapsed = (datetime.now(UTC) - self._stats.opened_at).total_seconds()
            stats['seconds_until_half_open'] = max(0, self.config.timeout_seconds - elapsed)
        
        return stats
    
    def reset(self):
        """Reset circuit breaker to initial state."""
        logger.info(f"🔄 Resetting circuit breaker for {self.server_name}")
        self._stats = CircuitBreakerStats(state=CircuitState.CLOSED)
        self._recent_failures.clear()

