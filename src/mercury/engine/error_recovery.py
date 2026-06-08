"""Error recovery strategies for email sending."""

from typing import Optional, List, Dict, Any
from enum import Enum

from ..exceptions import SMTPAuthenticationError, is_transient_error
from ..utils.logging_context import get_context_logger

logger = get_context_logger(__name__)


class RecoveryStrategy(Enum):
    """Error recovery strategies."""

    RETRY_SAME = "retry_same"  # Retry with same SMTP server
    SWITCH_SERVER = "switch_server"  # Try different SMTP server
    FALLBACK_CHAIN = "fallback_chain"  # Try servers in order
    DELAY_RETRY = "delay_retry"  # Wait before retrying
    DEAD_LETTER = "dead_letter"  # Move to dead letter queue
    ALERT = "alert"  # Send alert to admin


class ErrorRecoveryDecision:
    """Decision about how to recover from an error."""

    def __init__(
        self,
        strategy: RecoveryStrategy,
        should_retry: bool,
        retry_delay: float = 0,
        alternative_smtp: Optional[str] = None,
        reason: str = "",
    ):
        """
        Initialize recovery decision.

        Args:
            strategy: Recovery strategy to use
            should_retry: Whether to retry the operation
            retry_delay: Seconds to wait before retry
            alternative_smtp: Alternative SMTP server name
            reason: Reason for the decision
        """
        self.strategy = strategy
        self.should_retry = should_retry
        self.retry_delay = retry_delay
        self.alternative_smtp = alternative_smtp
        self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "should_retry": self.should_retry,
            "retry_delay": self.retry_delay,
            "alternative_smtp": self.alternative_smtp,
            "reason": self.reason,
        }


class ErrorRecoveryManager:
    """Manages error recovery strategies."""

    def __init__(
        self,
        available_smtp_servers: Optional[List[str]] = None,
        max_smtp_switches: int = 3,
        enable_dead_letter: bool = True,
    ):
        """
        Initialize error recovery manager.

        Args:
            available_smtp_servers: List of available SMTP server names
            max_smtp_switches: Maximum server switches per email
            enable_dead_letter: Enable dead letter queue
        """
        self.available_smtp_servers = available_smtp_servers or []
        self.max_smtp_switches = max_smtp_switches
        self.enable_dead_letter = enable_dead_letter

        # Track switches per correlation_id
        self._switch_counts: Dict[str, int] = {}
        self._server_attempts: Dict[str, List[str]] = {}  # correlation_id -> [servers]

    def decide_recovery(
        self,
        error: Exception,
        current_smtp: Optional[str] = None,
        correlation_id: Optional[str] = None,
        retry_count: int = 0,
    ) -> ErrorRecoveryDecision:
        """
        Decide how to recover from an error.

        Args:
            error: Exception that occurred
            current_smtp: Current SMTP server name
            correlation_id: Email correlation ID
            retry_count: Number of retries so far

        Returns:
            Recovery decision
        """
        # Check if error is transient
        transient = is_transient_error(error)

        # For permanent errors, go to dead letter immediately
        if not transient:
            if isinstance(error, SMTPAuthenticationError):
                return ErrorRecoveryDecision(
                    strategy=RecoveryStrategy.ALERT,
                    should_retry=False,
                    reason=f"Authentication error - requires config fix: {error}",
                )

            return ErrorRecoveryDecision(
                strategy=RecoveryStrategy.DEAD_LETTER,
                should_retry=False,
                reason=f"Permanent error: {error.__class__.__name__}",
            )

        # For transient errors, decide based on context

        # Check if we've exhausted server switches
        if correlation_id and correlation_id in self._switch_counts:
            switches = self._switch_counts[correlation_id]
            if switches >= self.max_smtp_switches:
                logger.warning(
                    "Max SMTP switches reached", correlation_id=correlation_id, switches=switches
                )
                return ErrorRecoveryDecision(
                    strategy=RecoveryStrategy.DELAY_RETRY,
                    should_retry=True,
                    retry_delay=60.0,  # Wait 1 minute
                    reason=f"Max switches ({switches}) reached, delaying retry",
                )

        # Check if we can switch SMTP servers
        if current_smtp and len(self.available_smtp_servers) > 1:
            # Get servers already tried
            tried_servers = set(self._server_attempts.get(correlation_id, []))
            tried_servers.add(current_smtp)

            # Find untried servers
            untried = [s for s in self.available_smtp_servers if s not in tried_servers]

            if untried:
                alternative = untried[0]

                # Track the switch
                if correlation_id:
                    self._switch_counts[correlation_id] = (
                        self._switch_counts.get(correlation_id, 0) + 1
                    )
                    if correlation_id not in self._server_attempts:
                        self._server_attempts[correlation_id] = []
                    self._server_attempts[correlation_id].append(current_smtp)

                logger.info(
                    "🔄 Switching SMTP server",
                    from_server=current_smtp,
                    to_server=alternative,
                    correlation_id=correlation_id,
                )

                return ErrorRecoveryDecision(
                    strategy=RecoveryStrategy.SWITCH_SERVER,
                    should_retry=True,
                    alternative_smtp=alternative,
                    reason=f"Switching from {current_smtp} to {alternative}",
                )

        # Default: delay and retry
        delay = min(5 * (retry_count + 1), 60)  # Exponential up to 60s

        return ErrorRecoveryDecision(
            strategy=RecoveryStrategy.DELAY_RETRY,
            should_retry=True,
            retry_delay=delay,
            reason=f"Transient error, retry in {delay}s",
        )

    def clear_tracking(self, correlation_id: str):
        """
        Clear tracking for a correlation ID.

        Args:
            correlation_id: Correlation ID to clear
        """
        self._switch_counts.pop(correlation_id, None)
        self._server_attempts.pop(correlation_id, None)

    def get_attempted_servers(self, correlation_id: str) -> List[str]:
        """
        Get list of servers already attempted for an email.

        Args:
            correlation_id: Correlation ID

        Returns:
            List of server names
        """
        return self._server_attempts.get(correlation_id, [])

    def get_statistics(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        return {
            "active_recoveries": len(self._switch_counts),
            "total_switches": sum(self._switch_counts.values()),
            "available_servers": len(self.available_smtp_servers),
        }
